DEFAULT_PROVIDER = "deepseek"


PROVIDERS = {
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
    "gemini": {
        "backend": "openai_compatible",
        "api_key": "",
        "api_key_env": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "base_url_env": "GEMINI_BASE_URL",
        "model": "gemini-2.5-flash",
        "model_env": "AGENT_MODEL",
    },
    "claude": {
        "backend": "litellm",
        "api_key": "",
        "api_key_env": "ANTHROPIC_API_KEY",
        "model": "anthropic/claude-sonnet-4-5",
        "model_env": "AGENT_MODEL",
    },
}


DISABLE_TRACING_WITHOUT_OPENAI_KEY = True


# Telegram bridge.
# Create a bot with BotFather, then set TELEGRAM_BOT_TOKEN here or through env.
# Use `python -m mini_hermes telegram-bot --allow-any-chat`, send `/id`, then
# move that chat_id into TELEGRAM_ALLOWED_CHAT_IDS for normal locked-down use.
TELEGRAM_BOT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_ALLOWED_CHAT_IDS = []
TELEGRAM_POLLING_TIMEOUT = 30
TELEGRAM_REQUEST_TIMEOUT = 90
TELEGRAM_WORKSPACE = "."
TELEGRAM_AUTO_OBSERVE = False
TELEGRAM_MAX_STEPS = 8


# Optional local paths Mini Hermes may inspect in addition to the workspace.
LOCAL_READ_ALLOWED_PATHS = []


# Optional local paths Mini Hermes may write to in addition to the workspace.
# Keep this narrow: every path listed here can be created/overwritten by the agent.
LOCAL_WRITE_ALLOWED_PATHS = []
