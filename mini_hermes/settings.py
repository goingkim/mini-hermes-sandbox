from __future__ import annotations

import copy
import os
from dataclasses import dataclass

try:
    import config
except ModuleNotFoundError:
    config = None


DEFAULT_PROVIDERS = {
    "deepseek": {
        "backend": "openai_compatible",
        "api_key": "",
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "base_url_env": "DEEPSEEK_BASE_URL",
        "model": "deepseek-chat",
        "model_env": "AGENT_MODEL",
    },
    "openai": {
        "backend": "openai",
        "api_key": "",
        "api_key_env": "OPENAI_API_KEY",
        "model": "gpt-5.5",
        "model_env": "AGENT_MODEL",
    },
}


@dataclass(frozen=True)
class Settings:
    provider_name: str
    backend: str
    api_key: str
    api_key_env: str
    model: str
    base_url: str


@dataclass(frozen=True)
class TelegramSettings:
    bot_token: str
    bot_token_env: str
    allowed_chat_ids: tuple[str, ...]
    polling_timeout: int
    request_timeout: int
    workspace: str
    auto_observe: bool
    max_steps: int


def load_settings() -> Settings:
    providers = copy.deepcopy(DEFAULT_PROVIDERS)
    if config and hasattr(config, "PROVIDERS"):
        providers.update(copy.deepcopy(config.PROVIDERS))

    default_provider = getattr(config, "DEFAULT_PROVIDER", "deepseek") if config else "deepseek"
    provider_name = os.getenv("AGENT_PROVIDER", default_provider).lower()
    if provider_name not in providers:
        available = ", ".join(sorted(providers))
        raise SystemExit(f"Unknown AGENT_PROVIDER '{provider_name}'. Available providers: {available}")

    provider = providers[provider_name]
    api_key = os.getenv(provider.get("api_key_env", ""), provider.get("api_key", ""))
    model = os.getenv(provider.get("model_env", ""), provider.get("model", ""))
    base_url = os.getenv(provider.get("base_url_env", ""), provider.get("base_url", ""))

    return Settings(
        provider_name=provider_name,
        backend=provider.get("backend", "openai"),
        api_key=api_key,
        api_key_env=provider.get("api_key_env", ""),
        model=model,
        base_url=base_url,
    )


def load_telegram_settings() -> TelegramSettings:
    bot_token_env = str(_config_value("TELEGRAM_BOT_TOKEN_ENV", "TELEGRAM_BOT_TOKEN"))
    bot_token = os.getenv(bot_token_env, str(_config_value("TELEGRAM_BOT_TOKEN", "")))
    allowed_raw = os.getenv(
        "TELEGRAM_ALLOWED_CHAT_IDS",
        _config_value("TELEGRAM_ALLOWED_CHAT_IDS", ""),
    )
    polling_timeout = int(
        os.getenv(
            "TELEGRAM_POLLING_TIMEOUT",
            str(_config_value("TELEGRAM_POLLING_TIMEOUT", 30)),
        )
    )
    request_timeout = int(
        os.getenv(
            "TELEGRAM_REQUEST_TIMEOUT",
            str(_config_value("TELEGRAM_REQUEST_TIMEOUT", 90)),
        )
    )
    workspace = str(os.getenv("TELEGRAM_WORKSPACE", str(_config_value("TELEGRAM_WORKSPACE", "."))))
    auto_observe = _bool_env(
        "TELEGRAM_AUTO_OBSERVE",
        bool(_config_value("TELEGRAM_AUTO_OBSERVE", False)),
    )
    max_steps = int(os.getenv("TELEGRAM_MAX_STEPS", str(_config_value("TELEGRAM_MAX_STEPS", 8))))

    return TelegramSettings(
        bot_token=bot_token,
        bot_token_env=bot_token_env,
        allowed_chat_ids=_parse_chat_ids(allowed_raw),
        polling_timeout=max(1, polling_timeout),
        request_timeout=max(5, request_timeout),
        workspace=workspace,
        auto_observe=auto_observe,
        max_steps=max(1, max_steps),
    )


def _config_value(name: str, default: object) -> object:
    if config and hasattr(config, name):
        return getattr(config, name)
    return default


def _parse_chat_ids(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = str(value).replace(";", ",").split(",")
    return tuple(str(item).strip() for item in raw_items if str(item).strip())


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
