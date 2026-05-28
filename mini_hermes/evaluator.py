from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class RunScore:
    score: float
    reason: str
    metrics: dict[str, Any]


class RunEvaluator:
    def score_run(
        self,
        status: str,
        steps: list[dict[str, Any]],
        started_at: str,
        ended_at: str,
        final_answer: str,
    ) -> RunScore:
        errors = sum(1 for step in steps if step.get("status") != "success")
        tool_count = len(steps)
        elapsed = _elapsed_seconds(started_at, ended_at)
        completed = status == "success" and bool(final_answer.strip())
        blocked = status == "blocked"

        if blocked:
            score = 0.2
        elif not completed:
            score = 0.1
        else:
            score = 1.0
            score -= min(0.25, errors * 0.18)
            score -= min(0.20, max(0, tool_count - 3) * 0.03)
            score -= min(0.15, max(0.0, elapsed - 10.0) * 0.005)

        score = max(0.0, min(1.0, score))
        reason = (
            f"heuristic completed={completed}, tools={tool_count}, "
            f"errors={errors}, elapsed={elapsed:.2f}s, blocked={blocked}"
        )
        return RunScore(
            score=score,
            reason=reason,
            metrics={
                "completed": completed,
                "blocked": blocked,
                "tool_count": tool_count,
                "errors": errors,
                "elapsed_seconds": elapsed,
            },
        )


def _elapsed_seconds(started_at: str, ended_at: str) -> float:
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(ended_at)
    except ValueError:
        return 0.0
    return max(0.0, (end - start).total_seconds())
