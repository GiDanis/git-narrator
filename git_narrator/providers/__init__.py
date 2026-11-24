"""Provider drivers and unified factory for git-narrator."""

from typing import Any

from git_narrator.config import PROVIDER_SPECS, normalize_provider_name
from git_narrator.providers.anthropic import AnthropicProvider
from git_narrator.providers.base import BaseLLMProvider
from git_narrator.providers.gemini import GeminiProvider
from git_narrator.providers.ollama import OllamaProvider
from git_narrator.providers.openai import OpenAIProvider

__all__ = [
    "AnthropicProvider",
    "BaseLLMProvider",
    "GeminiProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "create_provider",
]


def create_provider(
    provider_name: str,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    **kwargs: Any,
) -> BaseLLMProvider:
    """Instantiate the appropriate LLM provider driver using canonical PROVIDER_SPECS."""
    canonical = normalize_provider_name(provider_name)
    spec = PROVIDER_SPECS.get(canonical)

    if spec is None and canonical != "vllm":
        supported = ", ".join(PROVIDER_SPECS.keys())
        raise ValueError(
            f"Unknown provider '{provider_name}'. Supported providers: {supported}, vllm."
        )

    effective_model = model or (spec.default_model if spec else "gpt-4.1-mini")
    effective_base_url = base_url or (spec.default_base_url if spec else "https://api.openai.com/v1")

    if canonical == "ollama":
        return OllamaProvider(
            model=effective_model,
            base_url=effective_base_url,
            **kwargs,
        )
    if canonical == "gemini":
        return GeminiProvider(
            model=effective_model,
            api_key=api_key,
            base_url=effective_base_url,
            **kwargs,
        )
    if canonical == "anthropic":
        return AnthropicProvider(
            model=effective_model,
            api_key=api_key,
            base_url=effective_base_url,
            **kwargs,
        )

    use_json_object = kwargs.pop("use_json_object", spec.use_json_object if spec else False)
    return OpenAIProvider(
        model=effective_model,
        api_key=api_key,
        base_url=effective_base_url,
        use_json_object=use_json_object,
        **kwargs,
    )
