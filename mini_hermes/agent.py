from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mini_hermes.evaluator import RunEvaluator
from mini_hermes.llm import LLMClient, build_llm
from mini_hermes.privacy import clean_text
from mini_hermes.settings import Settings, load_settings
from mini_hermes.store import MiniHermesStore
from mini_hermes.tools import (
    ToolContext,
    ToolRegistry,
    build_default_registry,
    capture_screen_observation,
    parse_tool_arguments,
)


@dataclass(frozen=True)
class RunResult:
    run_id: str
    final_answer: str
    score: float
    score_reason: str
    status: str


class MiniHermesAgent:
    def __init__(
        self,
        llm: LLMClient | None = None,
        settings: Settings | None = None,
        store: MiniHermesStore | None = None,
        registry: ToolRegistry | None = None,
        workspace: str | Path = ".",
        auto_observe: bool = True,
        max_steps: int = 8,
    ) -> None:
        self.settings = settings or load_settings()
        self.llm = llm or build_llm(self.settings)
        self.store = store or MiniHermesStore()
        self.registry = registry or build_default_registry()
        self.workspace = Path(workspace).resolve()
        self.auto_observe = auto_observe
        self.max_steps = max_steps
        self.evaluator = RunEvaluator()

    async def run(self, task: str, learn: bool = True) -> RunResult:
        task = clean_text(task)
        run_id = self.store.start_run(
            task=task,
            provider=self.settings.provider_name,
            model=self.settings.model,
        )
        context = ToolContext(store=self.store, run_id=run_id, workspace=self.workspace)
        messages = self._initial_messages(task)
        final_answer = ""
        status = "success"
        error = ""

        try:
            for step_index in range(1, self.max_steps + 1):
                assistant = await self.llm.complete(
                    messages=messages,
                    tools=self.registry.definitions(),
                    tool_choice="auto",
                    temperature=0.2,
                )
                messages.append(_assistant_message_for_history(assistant))

                tool_calls = assistant.get("tool_calls") or []
                if not tool_calls:
                    final_answer = str(assistant.get("content") or "").strip()
                    break

                for tool_call in tool_calls:
                    name = tool_call.get("function", {}).get("name", "")
                    arguments = parse_tool_arguments(tool_call.get("function", {}).get("arguments"))
                    before_observation_id = self._observe_before(run_id, name)
                    step_id = self.store.add_step(
                        run_id=run_id,
                        step_index=step_index,
                        tool_name=name,
                        arguments=arguments,
                        before_observation_id=before_observation_id,
                    )
                    result = self.registry.dispatch(name, arguments, context)
                    after_observation_id = self._observe_after(run_id, step_id, name, result)
                    step_status = "success" if result.get("ok", True) else "error"
                    self.store.finish_step(
                        step_id=step_id,
                        status=step_status,
                        result=result,
                        error=str(result.get("error", "")),
                        after_observation_id=after_observation_id,
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.get("id", f"tool-{step_id}"),
                            "name": name,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )

            if not final_answer:
                final_answer = "작업이 최대 단계에 도달했지만 최종 답변을 만들지 못했습니다."
                status = "error"
            elif _looks_blocked(final_answer):
                status = "blocked"
        except Exception as exc:
            status = "error"
            error = f"{type(exc).__name__}: {exc}"
            final_answer = error

        self.store.finish_run(run_id, status=status, final_answer=final_answer, error=error)
        run = self.store.get_run(run_id) or {}
        steps = self.store.get_steps(run_id)
        score = self.evaluator.score_run(
            status=status,
            steps=steps,
            started_at=str(run.get("started_at", "")),
            ended_at=str(run.get("ended_at", "")),
            final_answer=final_answer,
        )
        self.store.finish_run(
            run_id,
            status=status,
            final_answer=final_answer,
            score=score.score,
            score_reason=score.reason,
            error=error,
        )

        if learn and status == "success" and score.score >= 0.65:
            self.store.add_memory(
                text=f"Successful run for task '{task}'. Final answer: {final_answer[:500]}",
                kind="successful-run",
                tags="self-improvement,run",
                source_run_id=run_id,
                score=score.score,
            )

        return RunResult(
            run_id=run_id,
            final_answer=final_answer,
            score=score.score,
            score_reason=score.reason,
            status=status,
        )

    def _initial_messages(self, task: str) -> list[dict[str, Any]]:
        snippets = self._context_snippets(task)
        return [
            {
                "role": "system",
                "content": (
                    "You are Mini Hermes, a Korean-speaking research agent. "
                    "Use tools when they reduce uncertainty or perform the requested local action. "
                    "Your tool calls, screen observations, results, and reward scores are persisted "
                    "for later research. Do not reveal hidden chain-of-thought. "
                    "Answer in Korean unless the user asks otherwise.\n\n"
                    f"Available tools:\n{self.registry.describe()}\n\n"
                    f"Relevant prior memories:\n{snippets}"
                ),
            },
            {"role": "user", "content": task},
        ]

    def _context_snippets(self, task: str) -> str:
        memories = self.store.search_memories(task, limit=5)
        if not memories:
            return "No prior memory."
        return "\n".join(f"- {memory['kind']}: {memory['text']}" for memory in memories)

    def _observe_before(self, run_id: str, tool_name: str) -> str:
        if not self.auto_observe:
            return ""
        return capture_screen_observation(
            self.store,
            run_id,
            note=f"before tool {tool_name}",
            action_label=f"before:{tool_name}",
        )

    def _observe_after(
        self,
        run_id: str,
        step_id: int,
        tool_name: str,
        result: dict[str, Any],
    ) -> str:
        if not self.auto_observe:
            return ""
        return capture_screen_observation(
            self.store,
            run_id,
            note=f"after tool {tool_name}: {str(result)[:300]}",
            action_label=f"after:{tool_name}",
            step_id=step_id,
        )


def _assistant_message_for_history(assistant: dict[str, Any]) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": assistant.get("content") or "",
    }
    if assistant.get("tool_calls"):
        message["tool_calls"] = assistant["tool_calls"]
    return message


def _looks_blocked(answer: str) -> bool:
    lowered = answer.lower()
    markers = (
        "직접 제어할 수 없습니다",
        "직접 조작 불가",
        "실시간 수신 불가",
        "연동 불가",
        "할 수 없습니다",
        "지원하지 않습니다",
        "cannot",
        "can't",
        "unable to",
        "not possible",
    )
    return any(marker in lowered for marker in markers)
