from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from dataset.storage import EpisodeStore


@dataclass(frozen=True)
class EpisodeScore:
    episode_id: str
    score: float
    reason: str
    metrics: dict[str, Any]


class RuleBasedEpisodeScorer:
    def __init__(self, store: EpisodeStore | None = None) -> None:
        self.store = store or EpisodeStore()

    def score(self, episode_id: str, persist: bool = True) -> EpisodeScore:
        episode = self.store.get_episode(episode_id)
        if not episode:
            raise ValueError(f"unknown episode_id: {episode_id}")

        frames = self.store.get_frames(episode_id)
        events = self.store.get_input_events(episode_id)
        tool_calls = self.store.get_tool_calls(episode_id)
        observations = self.store.get_observations(episode_id)
        status = str(episode.get("status") or "")
        started_at = float(episode.get("started_at") or 0.0)
        ended_at = float(episode.get("ended_at") or started_at)
        duration = max(0.0, ended_at - started_at)
        key_events = sum(1 for event in events if event.get("kind") == "keyboard")
        mouse_events = sum(1 for event in events if event.get("kind") == "mouse")
        clicks = sum(1 for event in events if str(event.get("action", "")).endswith("_down"))
        tool_errors = sum(1 for call in tool_calls if call.get("status") not in {"recorded", "success", "completed"})
        recorder_errors = sum(1 for item in observations if item.get("kind") == "recorder_error")

        score = 1.0 if status == "completed" else 0.45
        if not frames:
            score -= 0.35
        if duration <= 0:
            score -= 0.2
        if tool_errors:
            score -= min(0.25, tool_errors * 0.1)
        if recorder_errors:
            score -= 0.35
        if len(events) > 2000:
            score -= 0.1
        if duration > 300:
            score -= 0.1
        score = max(0.0, min(1.0, score))

        metrics = {
            "status": status,
            "duration_seconds": duration,
            "frame_count": len(frames),
            "input_event_count": len(events),
            "keyboard_event_count": key_events,
            "mouse_event_count": mouse_events,
            "click_count": clicks,
            "tool_call_count": len(tool_calls),
            "tool_error_count": tool_errors,
            "recorder_error_count": recorder_errors,
        }
        reason = (
            f"rule_based status={status}, frames={len(frames)}, inputs={len(events)}, "
            f"tool_errors={tool_errors}, recorder_errors={recorder_errors}, duration={duration:.2f}s"
        )
        result = EpisodeScore(
            episode_id=episode_id,
            score=score,
            reason=reason,
            metrics=metrics,
        )
        if persist:
            self.store.add_score(
                episode_id=episode_id,
                score=result.score,
                reason=result.reason,
                metrics=result.metrics,
            )
        return result

    def latest_score_text(self, episode_id: str) -> str:
        row = self.store.get_latest_score(episode_id)
        if not row:
            return "no score recorded"
        metrics = json.loads(str(row.get("metrics_json") or "{}"))
        return f"score={float(row['score']):.3f} reason={row['reason']} metrics={metrics}"
