"""OpenAI-compatible LLM provider driver (OpenAI, Groq, DeepSeek, OpenRouter, vLLM)."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import BaseModel

from git_narrator.providers.base import BaseLLMProvider, resolve_schema_dict
from git_narrator.transport import aiter_sse_data, send_streaming_with_retry


def prepare_openai_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize JSON schema to satisfy OpenAI strict structured outputs.

    OpenAI strict mode mandates:
    - Dereferenced objects (no sibling keywords alongside '$ref')
    - 'additionalProperties': false on every object schema
    - Every key in 'properties' listed in 'required'
    - No unsupported keywords like 'default', '$defs', '$schema', 'title'
    """
    defs = schema.get("$defs", {})

    def transform(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref_path = str(node["$ref"])
                if ref_path.startswith("#/$defs/"):
                    def_name = ref_path.split("/")[-1]
                    if def_name in defs:
                        return transform(defs[def_name])

            out: dict[str, Any] = {}
            for k, v in node.items():
                if k in ("$defs", "$schema", "title", "default"):
                    continue
                out[k] = transform(v)

            if out.get("type") == "object" or "properties" in out:
                props = out.get("properties")
                if isinstance(props, dict):
                    out["required"] = list(props.keys())
                out["additionalProperties"] = False
                out.setdefault("type", "object")
            return out

        if isinstance(node, list):
            return [transform(item) for item in node]
        return node

    result = transform(schema)
    return result if isinstance(result, dict) else {}


class OpenAIProvider(BaseLLMProvider):
    """Driver for OpenAI and OpenAI-compatible inference APIs."""

    def __init__(
        self,
        model: str = "gpt-4.1-mini",
        api_key: str | None = None,
        base_url: str | None = "https://api.openai.com/v1",
        timeout: float = 90.0,
        strict_schema: bool = True,
        use_json_object: bool = False,
        temperature: float = 0.1,
        client: httpx.AsyncClient | None = None,
    ):
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url or "https://api.openai.com/v1",
            timeout=timeout,
            client=client,
        )
        self.strict_schema = strict_schema
        self.use_json_object = use_json_object
        self.temperature = temperature
        self.supports_native_schema = not use_json_object

    def build_payload(
        self,
        system_prompt: str,
        user_prompt: str,
        target_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Build request payload for /chat/completions."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "stream": True,
        }

        if self.use_json_object:
            payload["response_format"] = {"type": "json_object"}
        elif target_schema:
            formatted_schema = (
                prepare_openai_strict_schema(target_schema)
                if self.strict_schema
                else target_schema
            )
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "git_narrator_report",
                    "strict": self.strict_schema,
                    "schema": formatted_schema,
                },
            }

        return payload

    async def stream_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any] | type[BaseModel] | None = None,
    ) -> AsyncIterator[str]:
        """Stream structured JSON response chunks via SSE."""
        target_schema = resolve_schema_dict(json_schema)
        endpoint = f"{self.base_url}/chat/completions"

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = self.build_payload(system_prompt, user_prompt, target_schema)

        response = await send_streaming_with_retry(
            self.client,
            "POST",
            endpoint,
            headers=headers,
            json_payload=payload,
        )
        try:
            async for sse_event in aiter_sse_data(response, stop_sentinel="[DONE]"):
                try:
                    event_data = json.loads(sse_event)
                except json.JSONDecodeError:
                    continue

                choices = event_data.get("choices", [])
                if not choices:
                    continue

                delta = choices[0].get("delta", {})
                content = delta.get("content")
                if content:
                    yield content
        finally:
            await response.aclose()
