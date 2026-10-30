"""Anthropic Claude LLM provider driver using tool-use structured streaming."""

import json
from typing import Any, AsyncIterator, Optional, Type
import httpx
from pydantic import BaseModel

from git_narrator.providers.base import BaseLLMProvider, resolve_schema_dict
from git_narrator.transport import aiter_sse_data


class AnthropicProvider(BaseLLMProvider):
    """Driver for Anthropic Claude messages API using tool_choice for structured output."""

    def __init__(
        self,
        model: str = "claude-3-5-sonnet-20241022",
        api_key: Optional[str] = None,
        base_url: Optional[str] = "https://api.anthropic.com",
        max_tokens: int = 4096,
        timeout: float = 90.0,
        client: Optional[httpx.AsyncClient] = None,
    ):
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url or "https://api.anthropic.com",
            timeout=timeout,
            client=client,
        )
        self.max_tokens = max_tokens

    def build_payload(
        self,
        system_prompt: str,
        user_prompt: str,
        target_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Build request payload for /v1/messages with tool_choice."""
        tool_name = "emit_git_narrator_report"
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_prompt},
            ],
            "tools": [
                {
                    "name": tool_name,
                    "description": "Emit structured GitNarratorReport analysis.",
                    "input_schema": target_schema,
                }
            ],
            "tool_choice": {
                "type": "tool",
                "name": tool_name,
            },
            "stream": True,
        }

    async def stream_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any] | Type[BaseModel] | None = None,
    ) -> AsyncIterator[str]:
        """Stream structured JSON chunks from Anthropic tool input stream."""
        target_schema = resolve_schema_dict(json_schema)
        endpoint = f"{self.base_url}/v1/messages"

        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key

        payload = self.build_payload(system_prompt, user_prompt, target_schema)

        request = self.client.build_request(
            method="POST",
            url=endpoint,
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

                event_type = event_data.get("type")
                if event_type == "content_block_delta":
                    delta = event_data.get("delta", {})
                    delta_type = delta.get("type")
                    if delta_type == "input_json_delta":
                        partial_json = delta.get("partial_json", "")
                        if partial_json:
                            yield partial_json
                    elif delta_type == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            yield text
        finally:
            await response.aclose()
