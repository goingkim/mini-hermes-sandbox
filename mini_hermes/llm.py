from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from mini_hermes.settings import Settings


class LLMClient(Protocol):
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        ...


@dataclass
class OpenAICompatibleLLM:
    settings: Settings

    def __post_init__(self) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError("OpenAI backend requires openai to be installed") from exc

        kwargs: dict[str, Any] = {"api_key": self.settings.api_key}
        if self.settings.base_url:
            kwargs["base_url"] = self.settings.base_url
        self.client = AsyncOpenAI(**kwargs)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        response = await self.client.chat.completions.create(**kwargs)
        message = response.choices[0].message
        tool_calls = []
        for call in message.tool_calls or []:
            tool_calls.append(
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments or "{}",
                    },
                }
            )
        return {
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": tool_calls,
            "usage": response.usage.model_dump() if response.usage else {},
        }


@dataclass
class LiteLLMLLM:
    settings: Settings

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        try:
            from litellm import acompletion
        except ImportError as exc:
            raise RuntimeError("LiteLLM backend requires litellm to be installed") from exc

        kwargs: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": temperature,
            "api_key": self.settings.api_key or None,
        }
        if self.settings.base_url:
            kwargs["api_base"] = self.settings.base_url
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        response = await acompletion(**kwargs)
        message = response["choices"][0]["message"]
        return {
            "role": "assistant",
            "content": message.get("content") or "",
            "tool_calls": message.get("tool_calls") or [],
            "usage": response.get("usage") or {},
        }


class FakeLLM:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "messages": messages,
                "tools": tools or [],
                "tool_choice": tool_choice,
                "temperature": temperature,
            }
        )
        if not self.responses:
            return {"role": "assistant", "content": "No fake response configured.", "tool_calls": []}
        response = self.responses.pop(0)
        return {
            "role": "assistant",
            "content": response.get("content", ""),
            "tool_calls": response.get("tool_calls", []),
            "usage": response.get("usage", {}),
        }


def build_llm(settings: Settings) -> LLMClient:
    if not settings.api_key:
        raise SystemExit(
            f"API key is not set for provider '{settings.provider_name}'. "
            f"Set it in config.py or with ${settings.api_key_env}."
        )
    if settings.backend == "litellm":
        return LiteLLMLLM(settings)
    if settings.backend in {"openai", "openai_compatible"}:
        return OpenAICompatibleLLM(settings)
    raise SystemExit(f"Unsupported provider backend: {settings.backend}")
