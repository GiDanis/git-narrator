"""Google Gemini LLM provider driver using v1beta streaming API."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import BaseModel

from git_narrator.providers.base import BaseLLMProvider, resolve_schema_dict
from git_narrator.transport import TransportError, aiter_sse_data, send_streaming_with_retry


def clean_gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert Pydantic JSON schema into Gemini OpenAPI 3.0 response_schema subset.

    - Dereferences `$defs/$ref`
    - Unwraps `anyOf: [<schema>, {"type": "null"}]` into `nullable: true`
    - Strips unsupported keywords (`$defs`, `$schema`, `title`, `default`, `additionalProperties`)
    """
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref_path = str(node["$ref"])
                if ref_path.startswith("#/$defs/"):
                    def_name = ref_path.split("/")[-1]
                    if def_name in defs:
                        return resolve(defs[def_name])

            # Unwrap Pydantic v2 Optional union: anyOf: [T, {"type": "null"}]
            if "anyOf" in node and isinstance(node["anyOf"], list):
                non_null = [
                    opt for opt in node["anyOf"]
                    if not (isinstance(opt, dict) and opt.get("type") == "null")
                ]
                has_null = len(non_null) < len(node["anyOf"])
                if len(non_null) == 1:
                    resolved = resolve(non_null[0])
                    if isinstance(resolved, dict):
                        if has_null:
                            resolved["nullable"] = True
                        if "description" in node and "description" not in resolved:
                            resolved["description"] = node["description"]
                        return resolved

            out: dict[str, Any] = {}
            for k, v in node.items():
                if k in ("$defs", "title", "$schema", "default", "additionalProperties"):
                    continue
                out[k] = resolve(v)

            if "required" in out and not out["required"]:
                out.pop("required", None)
            return out

        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    result = resolve(schema)
    if not isinstance(result, dict):
        return {}
    result.pop("$defs", None)
    result.pop("title", None)
    return result


class GeminiProvider(BaseLLMProvider):
    """Driver for Google Gemini API supporting structured streaming via SSE."""

    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        api_key: str | None = None,
        base_url: str | None = "https://generativelanguage.googleapis.com",
        timeout: float = 90.0,
        temperature: float = 0.1,
        client: httpx.AsyncClient | None = None,
    ):
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url or "https://generativelanguage.googleapis.com",
            timeout=timeout,
            client=client,
        )
        self.temperature = temperature

    def build_payload(
        self,
        system_prompt: str,
        user_prompt: str,
        target_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Build request payload for Gemini streamGenerateContent."""
        gemini_schema = clean_gemini_schema(target_schema)

        return {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}],
                }
            ],
            "system_instruction": {
                "parts": [{"text": system_prompt}],
            },
            "generationConfig": {
                "temperature": self.temperature,
                "response_mime_type": "application/json",
                "response_schema": gemini_schema,
            },
        }

    async def stream_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any] | type[BaseModel] | None = None,
    ) -> AsyncIterator[str]:
        """Stream structured JSON chunks from Gemini via SSE."""
        target_schema = resolve_schema_dict(json_schema)
        endpoint = f"{self.base_url}/v1beta/models/{self.model}:streamGenerateContent"
        params = {"alt": "sse"}

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["x-goog-api-key"] = self.api_key

        payload = self.build_payload(system_prompt, user_prompt, target_schema)

        response = await send_streaming_with_retry(
            self.client,
            "POST",
            endpoint,
            params=params,
            headers=headers,
            json_payload=payload,
        )
        emitted_any = False
        try:
            async for sse_event in aiter_sse_data(response):
                try:
                    event_data = json.loads(sse_event)
                except json.JSONDecodeError:
                    continue

                prompt_feedback = event_data.get("promptFeedback", {})
                if prompt_feedback.get("blockReason"):
                    raise TransportError(
                        f"Gemini blocked request: {prompt_feedback.get('blockReason')}"
                    )

                candidates = event_data.get("candidates", [])
                for candidate in candidates:
                    parts = candidate.get("content", {}).get("parts", [])
                    for part in parts:
                        text = part.get("text", "")
                        if text:
                            emitted_any = True
                            yield text

                    finish_reason = candidate.get("finishReason")
                    if finish_reason in ("SAFETY", "RECITATION", "PROHIBITED_CONTENT") and not emitted_any:
                        raise TransportError(
                            f"Gemini halted output due to finishReason={finish_reason}."
                        )
        finally:
            await response.aclose()
