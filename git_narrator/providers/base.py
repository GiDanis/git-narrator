"""Abstract base class and utilities for LLM provider drivers."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Self

import httpx
from pydantic import BaseModel

from git_narrator.parser import parse_and_validate_report
from git_narrator.schemas import GitNarratorReport, get_report_json_schema
from git_narrator.transport import create_http_client


def resolve_schema_dict(
    schema: dict[str, Any] | type[BaseModel] | None,
) -> dict[str, Any]:
    """Resolve user schema argument into a JSON schema dictionary."""
    if schema is None:
        return get_report_json_schema()
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema.model_json_schema()
    if isinstance(schema, dict):
        return schema
    raise TypeError(f"Unsupported schema type: {type(schema)}")


class BaseLLMProvider(ABC):
    """Abstract base class for all LLM provider drivers."""

    supports_native_schema: bool = True

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 90.0,
        client: httpx.AsyncClient | None = None,
    ):
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout
        self._external_client = client
        self._owned_client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Return the active HTTP client, instantiating one if not provided."""
        if self._external_client is not None:
            return self._external_client
        if self._owned_client is None or self._owned_client.is_closed:
            self._owned_client = create_http_client(timeout=self.timeout)
        return self._owned_client

    async def close(self) -> None:
        """Close internally managed HTTP client if any."""
        if self._owned_client is not None and not self._owned_client.is_closed:
            await self._owned_client.aclose()
            self._owned_client = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self.close()

    @abstractmethod
    def stream_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any] | type[BaseModel] | None = None,
    ) -> AsyncIterator[str]:
        """Return an async iterator yielding structured JSON string chunks."""
        ...

    async def generate_report(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any] | type[BaseModel] | None = None,
    ) -> GitNarratorReport:
        """Stream the full LLM output, auto-repair, and return a validated GitNarratorReport."""
        chunks: list[str] = []
        async for chunk in self.stream_structured(system_prompt, user_prompt, json_schema):
            chunks.append(chunk)

        full_output = "".join(chunks)
        return parse_and_validate_report(full_output)
