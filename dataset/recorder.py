from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from dataset.schema import Episode
from dataset.screen import ScreenCapture
from dataset.storage import EpisodeStore
from dataset.win_input import WindowsInputRecorder


@dataclass(frozen=True)
class RecordingResult:
    episode_id: str
    task: str
    status: str
    duration_seconds: float
    frame_count: int
    input_event_count: int
    jsonl_path: str


class EpisodeRecorder:
    def __init__(self, store: EpisodeStore | None = None) -> None:
        self.store = store or EpisodeStore()

    def record(
        self,
        task: str,
        duration_seconds: float,
        fps: float = 1.0,
        capture_input: bool = True,
        record_key_text: bool = False,
        agent_plan: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RecordingResult:
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        if fps <= 0:
            raise ValueError("fps must be positive")

        episode = self.store.create_episode(
            task=task,
            metadata={
                "recorder": "dataset",
                "fps": fps,
                "capture_input": capture_input,
                "record_key_text": record_key_text,
                **(metadata or {}),
            },
        )
        if agent_plan:
            self.store.add_agent_plan(episode.episode_id, agent_plan, source="record-cli")

        input_count = 0

        def on_input_event(event: object) -> None:
            nonlocal input_count
            self.store.add_input_event(event)  # type: ignore[arg-type]
            input_count += 1

        input_recorder = None
        if capture_input:
            input_recorder = WindowsInputRecorder(
                episode_id=episode.episode_id,
                callback=on_input_event,
                record_key_text=record_key_text,
            )

        frame_count = 0
        started_at = time.monotonic()
        next_frame_at = started_at
        capture = ScreenCapture(self.store.frame_dir(episode.episode_id))
        status = "completed"

        try:
            if input_recorder:
                input_recorder.start()
            while time.monotonic() - started_at < duration_seconds:
                now = time.monotonic()
                if now >= next_frame_at:
                    frame = capture.capture(episode.episode_id, frame_count)
                    self.store.add_frame(frame)
                    frame_count += 1
                    next_frame_at = now + (1.0 / fps)
                time.sleep(0.01)
        except KeyboardInterrupt:
            status = "interrupted"
            raise
        except Exception as exc:
            status = "error"
            self.store.add_observation(
                episode.episode_id,
                kind="recorder_error",
                text=f"{type(exc).__name__}: {exc}",
            )
            raise
        finally:
            if input_recorder:
                input_recorder.stop()
            elapsed = time.monotonic() - started_at
            self.store.finish_episode(
                episode.episode_id,
                status=status,
                metadata={
                    "duration_seconds": elapsed,
                    "frame_count": frame_count,
                    "input_event_count": input_count,
                },
            )

        return RecordingResult(
            episode_id=episode.episode_id,
            task=episode.task,
            status=status,
            duration_seconds=time.monotonic() - started_at,
            frame_count=frame_count,
            input_event_count=input_count,
            jsonl_path=str(self.store.jsonl_path(episode.episode_id).resolve()),
        )

    def create_empty_episode(
        self,
        task: str,
        agent_plan: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Episode:
        episode = self.store.create_episode(task=task, metadata=metadata or {})
        if agent_plan:
            self.store.add_agent_plan(episode.episode_id, agent_plan, source="manual")
        return episode
