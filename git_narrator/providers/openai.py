"""OpenAI-compatible LLM provider driver (OpenAI, Groq, DeepSeek, OpenRouter, vLLM)."""

import json
from typing import Any, AsyncIterator, Optional, Type
import httpx
from pydantic import BaseModel

from git_narrator.providers.base import BaseLLMProvider, resolve_schema_dict
from git_narrator.transport import aiter_sse_data


class OpenAIProvider(BaseLLMProvider):
    """Driver for OpenAI and OpenAI-compatible inference APIs."""

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: Optional[str] = None,
        base_url: Optional[str] = "https://api.openai.com/v1",
        timeout: float = 90.0,
        strict_schema: bool = True,
        use_json_object: bool = False,
        client: Optional[httpx.AsyncClient] = None,
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
            "stream": True,
        }

        if self.use_json_object:
            payload["response_format"] = {"type": "json_object"}
        elif target_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "git_narrator_report",
                    "strict": self.strict_schema,
                    "schema": target_schema,
                },
            }

        return payload

    async def stream_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any] | Type[BaseModel] | None = None,
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

        request = self.client.build_request(
            method="POST",
            url=endpoint,
            headers=headers,
            json=payload,
        )

        response = await self.client.send(request, stream=True)
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
