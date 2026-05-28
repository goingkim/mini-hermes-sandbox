from __future__ import annotations

import re
from typing import Any


PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?82[-\s]?)?0?1[016789][-\s]?\d{3,4}[-\s]?\d{4}(?!\d)"
)
API_KEY_RE = re.compile(
    r"(?<![A-Za-z0-9_-])("
    r"sk-[A-Za-z0-9_-]{16,}|"
    r"sk_[A-Za-z0-9_-]{16,}|"
    r"AIza[A-Za-z0-9_-]{24,}|"
    r"xai-[A-Za-z0-9_-]{24,}|"
    r"ghp_[A-Za-z0-9]{16,}|"
    r"github_pat_[A-Za-z0-9_]{32,}"
    r")(?![A-Za-z0-9_-])"
)


def clean_text(text: str) -> str:
    return str(text).encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def redact_text(text: str, extra_secrets: list[str] | tuple[str, ...] = ()) -> str:
    text = clean_text(text)
    text = PHONE_RE.sub("[PHONE]", text)
    text = API_KEY_RE.sub("[SECRET]", text)
    for secret in extra_secrets:
        if secret:
            text = text.replace(str(secret), "[SECRET]")
    return text


def redact_obj(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_obj(item) for item in value]
    if isinstance(value, tuple):
        return [redact_obj(item) for item in value]
    if isinstance(value, dict):
        return {str(redact_obj(key)): redact_obj(item) for key, item in value.items()}
    return value
