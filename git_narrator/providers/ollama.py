"""Local Ollama LLM provider driver with context-window control and model discovery."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import BaseModel

from git_narrator.providers.base import BaseLLMProvider, resolve_schema_dict
from git_narrator.transport import TransportError, aiter_ndjson_lines, send_streaming_with_retry

PREFERRED_OLLAMA_PREFIXES = (
    "qwen2.5-coder",
    "qwen3",
    "qwen2.5",
    "deepseek-coder",
    "deepseek-r1",
    "codellama",
    "llama3.3",
    "llama3.2",
    "llama3.1",
    "gemma3",
    "gemma2",
    "mistral",
    "phi4",
)


def discover_ollama_models(base_url: str = "http://localhost:11434", timeout: float = 0.6) -> list[str]:
    """Query local Ollama /api/tags to discover pulled model names without raising."""
    url = f"{base_url.rstrip('/')}/api/tags"
    if not url.startswith(("http://", "https://")):
        return []
    try:
        resp = httpx.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        models = data.get("models", [])
        return [str(m["name"]) for m in models if isinstance(m, dict) and m.get("name")]
    except (httpx.HTTPError, TimeoutError, OSError, ValueError):
        return []


def select_best_ollama_model(
    installed_models: list[str],
    preferred: str = "qwen2.5-coder:7b",
) -> str:
    """Select the highest-priority installed Ollama model, falling back to preferred default."""
    if not installed_models:
        return preferred
    if preferred in installed_models:
        return preferred

    for prefix in PREFERRED_OLLAMA_PREFIXES:
        for name in installed_models:
            if name.lower().startswith(prefix):
                return name
    return installed_models[0]


class OllamaProvider(BaseLLMProvider):
    """Driver for local Ollama instances supporting structured JSON schema streaming."""

    def __init__(
        self,
        model: str = "qwen2.5-coder:7b",
        base_url: str | None = "http://localhost:11434",
        num_ctx: int = 16384,
        temperature: float = 0.1,
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
        self.num_ctx = num_ctx
        self.temperature = temperature

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
            "options": {
                "num_ctx": self.num_ctx,
                "temperature": self.temperature,
            },
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

        response = await send_streaming_with_retry(
            self.client,
            "POST",
            endpoint,
            headers={"Content-Type": "application/json"},
            json_payload=payload,
            max_retries=1,
        )
        try:
            async for line in aiter_ndjson_lines(response):
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if "error" in chunk:
                    raise TransportError(f"Ollama error: {chunk['error']}")

                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content

                if chunk.get("done", False):
                    break
        finally:
            await response.aclose()
