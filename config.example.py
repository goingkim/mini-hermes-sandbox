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
