"""Provider drivers for git-narrator."""

from typing import Any, Optional

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
    """Factory to instantiate the appropriate LLM provider.

    Args:
        provider_name: One of 'ollama', 'gemini', 'openai', 'anthropic', 'groq', 'deepseek', 'openrouter'.
        model: Optional model name override.
        api_key: Optional API key.
        base_url: Optional custom base URL.
        **kwargs: Additional provider-specific kwargs.

    Returns:
        Instantiated BaseLLMProvider subclass.
    """
    normalized = provider_name.strip().lower()

    if normalized == "ollama":
        return OllamaProvider(
            model=model or "llama3.2",
            base_url=base_url,
            **kwargs,
        )
    elif normalized in ("gemini", "google"):
        return GeminiProvider(
            model=model or "gemini-1.5-flash",
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )
    elif normalized in ("openai", "groq", "deepseek", "openrouter", "vllm"):
        default_base_urls = {
            "openai": "https://api.openai.com/v1",
            "groq": "https://api.groq.com/openai/v1",
            "deepseek": "https://api.deepseek.com/v1",
            "openrouter": "https://openrouter.ai/api/v1",
        }
        effective_base_url = base_url or default_base_urls.get(normalized, "https://api.openai.com/v1")
        default_models = {
            "openai": "gpt-4o",
            "groq": "llama-3.3-70b-versatile",
            "deepseek": "deepseek-chat",
            "openrouter": "anthropic/claude-3.5-sonnet",
        }
        effective_model = model or default_models.get(normalized, "gpt-4o")
        return OpenAIProvider(
            model=effective_model,
            api_key=api_key,
            base_url=effective_base_url,
            **kwargs,
        )
    elif normalized in ("anthropic", "claude"):
        return AnthropicProvider(
            model=model or "claude-3-5-sonnet-20241022",
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )
    else:
        raise ValueError(
            f"Unknown provider '{provider_name}'. Supported providers: ollama, gemini, openai, groq, deepseek, openrouter, anthropic."
        )
