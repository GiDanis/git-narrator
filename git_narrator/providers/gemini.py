"""Google Gemini LLM provider driver using v1beta streaming API."""

import json
from typing import Any, AsyncIterator, Optional, Type
import httpx
from pydantic import BaseModel

from git_narrator.providers.base import BaseLLMProvider, resolve_schema_dict
from git_narrator.transport import aiter_sse_data


def clean_gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Dereference $defs/$ref and remove incompatible keys for Gemini response_schema."""
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref_path = str(node["$ref"])
                if ref_path.startswith("#/$defs/"):
                    def_name = ref_path.split("/")[-1]
                    if def_name in defs:
                        return resolve(defs[def_name])
                return node
            out = {}
            for k, v in node.items():
                if k in ("$defs", "title", "$schema"):
                    continue
                out[k] = resolve(v)
            return out
        elif isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    result = resolve(schema)
    result.pop("$defs", None)
    result.pop("title", None)
    return result


class GeminiProvider(BaseLLMProvider):
    """Driver for Google Gemini API supporting structured streaming via SSE."""

    def __init__(
        self,
        model: str = "gemini-1.5-flash",
        api_key: Optional[str] = None,
        base_url: Optional[str] = "https://generativelanguage.googleapis.com",
        timeout: float = 90.0,
        client: Optional[httpx.AsyncClient] = None,
    ):
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url or "https://generativelanguage.googleapis.com",
            timeout=timeout,
            client=client,
        )

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
                "response_mime_type": "application/json",
                "response_schema": gemini_schema,
            },
        }

    async def stream_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any] | Type[BaseModel] | None = None,
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

        request = self.client.build_request(
            method="POST",
            url=endpoint,
            params=params,
            headers=headers,
            json=payload,
        )

        response = await self.client.send(request, stream=True)
        try:
            async for sse_event in aiter_sse_data(response):
                try:
                    event_data = json.loads(sse_event)
                except json.JSONDecodeError:
                    continue

                candidates = event_data.get("candidates", [])
                for candidate in candidates:
                    parts = candidate.get("content", {}).get("parts", [])
                    for part in parts:
                        text = part.get("text", "")
                        if text:
                            yield text
        finally:
            await response.aclose()
