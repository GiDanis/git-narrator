"""Configuration management, provider registry, and auto-detection for git-narrator."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
from typing import Any
from urllib.parse import urlparse

GLOBAL_CONFIG_PATH = Path.home() / ".config" / "git-narrator" / "config.json"
LOCAL_CONFIG_NAME = ".gitnarrator.json"


@dataclass(frozen=True)
class ProviderSpec:
    """Canonical specification for a supported AI provider."""

    driver: str
    default_model: str
    default_base_url: str | None
    env_key: str | None
    recommended_diff_tokens: int
    use_json_object: bool = False


PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "ollama": ProviderSpec(
        driver="ollama",
        default_model="qwen2.5-coder:7b",
        default_base_url="http://localhost:11434",
        env_key=None,
        recommended_diff_tokens=8000,
    ),
    "gemini": ProviderSpec(
        driver="gemini",
        default_model="gemini-2.5-flash",
        default_base_url="https://generativelanguage.googleapis.com",
        env_key="GEMINI_API_KEY",
        recommended_diff_tokens=20000,
    ),
    "openai": ProviderSpec(
        driver="openai",
        default_model="gpt-4.1-mini",
        default_base_url="https://api.openai.com/v1",
        env_key="OPENAI_API_KEY",
        recommended_diff_tokens=16000,
    ),
    "anthropic": ProviderSpec(
        driver="anthropic",
        default_model="claude-haiku-5-5",
        default_base_url="https://api.anthropic.com",
        env_key="ANTHROPIC_API_KEY",
        recommended_diff_tokens=18000,
    ),
    "groq": ProviderSpec(
        driver="openai",
        default_model="llama-3.3-70b-versatile",
        default_base_url="https://api.groq.com/openai/v1",
        env_key="GROQ_API_KEY",
        recommended_diff_tokens=10000,
        use_json_object=True,
    ),
    "deepseek": ProviderSpec(
        driver="openai",
        default_model="deepseek-chat",
        default_base_url="https://api.deepseek.com/v1",
        env_key="DEEPSEEK_API_KEY",
        recommended_diff_tokens=14000,
        use_json_object=True,
    ),
    "openrouter": ProviderSpec(
        driver="openai",
        default_model="google/gemini-2.5-flash",
        default_base_url="https://openrouter.ai/api/v1",
        env_key="OPENROUTER_API_KEY",
        recommended_diff_tokens=16000,
        use_json_object=True,
    ),
}

PROVIDER_ALIASES: dict[str, str] = {
    "google": "gemini",
    "claude": "anthropic",
}


def normalize_provider_name(name: str) -> str:
    """Normalize provider alias into canonical registry key."""
    key = name.strip().lower()
    return PROVIDER_ALIASES.get(key, key)


def _ollama_url(config: dict[str, Any] | None = None) -> str:
    cfg = config or {}
    raw = os.environ.get("OLLAMA_HOST") or cfg.get("ollama_base_url") or cfg.get("base_url") or "http://localhost:11434"
    raw_str = str(raw).strip()
    if not raw_str.startswith(("http://", "https://")):
        raw_str = f"http://{raw_str}"
    return raw_str.rstrip("/")


def is_ollama_reachable(
    host: str = "127.0.0.1",
    port: int = 11434,
    timeout: float = 0.25,
    base_url: str | None = None,
) -> bool:
    """Fast TCP socket check to test whether local Ollama daemon is listening."""
    if base_url:
        parsed = urlparse(base_url)
        host = parsed.hostname or host
        port = parsed.port or (443 if parsed.scheme == "https" else 11434)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (TimeoutError, OSError):
        return False


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def load_global_config() -> dict[str, Any]:
    """Load only global configuration from ~/.config/git-narrator/config.json."""
    return _read_json_file(GLOBAL_CONFIG_PATH)


def load_config() -> dict[str, Any]:
    """Load merged configuration from global and local project `.gitnarrator.json`."""
    config = load_global_config()
    config.update(_read_json_file(Path.cwd() / LOCAL_CONFIG_NAME))
    return config


def save_global_config(data: dict[str, Any]) -> None:
    """Persist user preferences strictly into global config (never leaks local overrides)."""
    GLOBAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    current = load_global_config()
    current.update(data)
    GLOBAL_CONFIG_PATH.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")


def _resolve_api_key_and_base(
    prov: str,
    config: dict[str, Any],
    override_model: str | None = None,
    auto_discover_ollama: bool = False,
) -> tuple[str, str, str | None, str | None]:
    canonical = normalize_provider_name(prov)
    spec = PROVIDER_SPECS.get(canonical)

    if spec is None:
        key = config.get("api_key") or os.environ.get(f"{canonical.upper()}_API_KEY")
        return canonical, override_model or config.get("model") or "gpt-4.1-mini", key, config.get("base_url")

    # Resolve base_url cleanly
    if canonical == "ollama":
        base_url: str | None = _ollama_url(config)
    elif canonical == "openai":
        base_url = os.environ.get("OPENAI_BASE_URL") or config.get("openai_base_url") or config.get("base_url") or spec.default_base_url
    else:
        base_url = config.get(f"{canonical}_base_url") or config.get("base_url") or spec.default_base_url

    # Resolve API key
    api_key: str | None = None
    if spec.env_key:
        api_key = os.environ.get(spec.env_key) or config.get(f"{canonical}_api_key") or config.get("api_key")

    # Resolve model
    configured_model = config.get(f"{canonical}_model") or (
        config.get("model") if normalize_provider_name(str(config.get("provider", ""))) == canonical else None
    )
    model = override_model or configured_model

    if not model and canonical == "ollama" and auto_discover_ollama:
        from git_narrator.providers.ollama import discover_ollama_models, select_best_ollama_model

        installed = discover_ollama_models(base_url or "http://localhost:11434")
        model = select_best_ollama_model(installed, preferred=spec.default_model)

    return canonical, model or spec.default_model, api_key, base_url


def resolve_provider_and_model(
    forced_local: bool = False,
    override_provider: str | None = None,
    override_model: str | None = None,
    auto_discover_ollama: bool = True,
) -> tuple[str, str, str | None, str | None]:
    """Resolve active canonical provider name, model, API key, and base URL.

    Resolution precedence:
    1. `--local` flag (forces Ollama)
    2. `--provider` CLI flag
    3. Configured `"provider"` in `.gitnarrator.json` / `~/.config/git-narrator/config.json`
    4. Auto-detection: running Ollama -> GEMINI_API_KEY -> OPENAI_API_KEY -> ANTHROPIC_API_KEY -> GROQ_API_KEY -> DEEPSEEK_API_KEY -> OPENROUTER_API_KEY
    """
    config = load_config()

    if forced_local:
        return _resolve_api_key_and_base(
            "ollama", config, override_model=override_model, auto_discover_ollama=auto_discover_ollama
        )

    if override_provider:
        return _resolve_api_key_and_base(
            override_provider, config, override_model=override_model, auto_discover_ollama=auto_discover_ollama
        )

    if config.get("provider"):
        return _resolve_api_key_and_base(
            str(config["provider"]), config, override_model=override_model, auto_discover_ollama=auto_discover_ollama
        )

    # Automatic detection cascade
    ollama_base = _ollama_url(config)
    if is_ollama_reachable(base_url=ollama_base):
        return _resolve_api_key_and_base(
            "ollama", config, override_model=override_model, auto_discover_ollama=auto_discover_ollama
        )

    for candidate in ("gemini", "openai", "anthropic", "groq", "deepseek", "openrouter"):
        spec = PROVIDER_SPECS[candidate]
        if spec.env_key and os.environ.get(spec.env_key):
            return _resolve_api_key_and_base(
                candidate, config, override_model=override_model, auto_discover_ollama=False
            )

    # Default offline fallback to Ollama
    return _resolve_api_key_and_base(
        "ollama", config, override_model=override_model, auto_discover_ollama=False
    )
