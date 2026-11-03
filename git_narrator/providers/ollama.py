"""Local Ollama LLM provider driver."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import BaseModel

from git_narrator.providers.base import BaseLLMProvider, resolve_schema_dict
from git_narrator.transport import aiter_ndjson_lines


class OllamaProvider(BaseLLMProvider):
    """Driver for local Ollama instances supporting structured JSON schema streaming."""

    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str | None = "http://localhost:11434",
        timeout: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ):
        super().__init__(
            model=model,
            api_key=None,
            base_url=base_url or "http://localhost:11434",
            timeout=timeout,
            client=client,
        )

    def build_payload(
        self,
        system_prompt: str,
        user_prompt: str,
        target_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Build request payload for Ollama /api/chat."""
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": True,
            "format": target_schema,
        }

    async def stream_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any] | type[BaseModel] | None = None,
    ) -> AsyncIterator[str]:
        """Stream structured JSON response chunks from Ollama."""
        target_schema = resolve_schema_dict(json_schema)
        endpoint = f"{self.base_url}/api/chat"
        payload = self.build_payload(system_prompt, user_prompt, target_schema)

        request = self.client.build_request(
            method="POST",
            url=endpoint,
            json=payload,
            headers={"Content-Type": "application/json"},
        )

        response = await self.client.send(request, stream=True)
        try:
            async for line in aiter_ndjson_lines(response):
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue

                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content

                if chunk.get("done", False):
                    break
        finally:
            await response.aclose()
