"""Configuration management and provider auto-detection for git-narrator."""

import json
import os
import socket
from pathlib import Path
from typing import Any

GLOBAL_CONFIG_PATH = Path.home() / ".config" / "git-narrator" / "config.json"
LOCAL_CONFIG_NAME = ".gitnarrator.json"


def is_ollama_reachable(host: str = "127.0.0.1", port: int = 11434, timeout: float = 0.2) -> bool:
    """Performs a fast TCP socket check to see if Ollama is running locally."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (TimeoutError, OSError):
        return False


def load_config() -> dict[str, Any]:
    """Loads combined configuration from global and local project files."""
    config: dict[str, Any] = {}

    if GLOBAL_CONFIG_PATH.exists():
        try:
            with open(GLOBAL_CONFIG_PATH, "r", encoding="utf-8") as f:
                config.update(json.load(f))
        except Exception:
            pass

    # Check local repo config
    local_path = Path.cwd() / LOCAL_CONFIG_NAME
    if local_path.exists():
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                config.update(json.load(f))
        except Exception:
            pass

    return config


def save_global_config(data: dict[str, Any]) -> None:
    """Saves user preferences to ~/.config/git-narrator/config.json."""
    GLOBAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    current = load_config()
    current.update(data)
    with open(GLOBAL_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)


def resolve_provider_and_model(
    forced_local: bool = False,
    override_provider: str | None = None,
    override_model: str | None = None,
) -> tuple[str, str, str | None, str | None]:
    """Resolves the active provider, model name, API key, and base URL.
    
    Returns: (provider_name, model_name, api_key, base_url)
    
    Order of Resolution:
    1. CLI flags (`--local` forces Ollama)
    2. Explicit user config in ~/.config/git-narrator/config.json
    3. Auto-detection:
       a. Local Ollama if running on localhost:11434
       b. GEMINI_API_KEY
       c. OPENAI_API_KEY
       d. ANTHROPIC_API_KEY
       e. GROQ_API_KEY
    """
    config = load_config()

    if forced_local:
        model = override_model or config.get("ollama_model", "qwen2.5-coder:7b")
        base_url = config.get("ollama_base_url", "http://localhost:11434")
        return "ollama", model, None, base_url

    if override_provider:
        prov = override_provider.lower()
        if prov == "ollama":
            return "ollama", override_model or "qwen2.5-coder:7b", None, "http://localhost:11434"
        elif prov == "gemini":
            key = os.environ.get("GEMINI_API_KEY") or config.get("gemini_api_key")
            return "gemini", override_model or "gemini-2.0-flash", key, None
        elif prov == "openai":
            key = os.environ.get("OPENAI_API_KEY") or config.get("openai_api_key")
            base = os.environ.get("OPENAI_BASE_URL") or config.get("openai_base_url")
            return "openai", override_model or "gpt-4o-mini", key, base
        elif prov == "anthropic":
            key = os.environ.get("ANTHROPIC_API_KEY") or config.get("anthropic_api_key")
            return "anthropic", override_model or "claude-3-5-haiku-20241022", key, None
        elif prov == "groq":
            key = os.environ.get("GROQ_API_KEY") or config.get("groq_api_key")
            return "openai", override_model or "llama-3.3-70b-versatile", key, "https://api.groq.com/openai/v1"

    # User configured preference
    if "provider" in config:
        prov = config["provider"].lower()
        model = override_model or config.get("model")
        key = config.get("api_key") or os.environ.get(f"{prov.upper()}_API_KEY")
        base = config.get("base_url")
        return prov, model or "default", key, base

    # Automatic Detection Flow
    # 1. Local Ollama
    if is_ollama_reachable():
        return "ollama", "qwen2.5-coder:7b", None, "http://localhost:11434"

    # 2. Google Gemini
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini", "gemini-2.0-flash", os.environ["GEMINI_API_KEY"], None

    # 3. OpenAI
    if os.environ.get("OPENAI_API_KEY"):
        return "openai", "gpt-4o-mini", os.environ["OPENAI_API_KEY"], os.environ.get("OPENAI_BASE_URL")

    # 4. Anthropic
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic", "claude-3-5-haiku-20241022", os.environ["ANTHROPIC_API_KEY"], None

    # 5. Groq
    if os.environ.get("GROQ_API_KEY"):
        return "openai", "llama-3.3-70b-versatile", os.environ["GROQ_API_KEY"], "https://api.groq.com/openai/v1"

    # Default fallback to Ollama with friendly warning
    return "ollama", "qwen2.5-coder:7b", None, "http://localhost:11434"
