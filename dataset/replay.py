from __future__ import annotations

from dataclasses import dataclass

from dataset.storage import EpisodeStore
from dataset.win_input import WindowsInputReplayer


@dataclass(frozen=True)
class ReplayResult:
    episode_id: str
    dry_run: bool
    event_count: int
    summary: list[str]


class EpisodeReplayer:
    def __init__(self, store: EpisodeStore | None = None) -> None:
        self.store = store or EpisodeStore()
        self.input_replayer = WindowsInputReplayer()

    def replay(
        self,
        episode_id: str,
        dry_run: bool = True,
        speed: float = 1.0,
        start_delay: float = 2.0,
    ) -> ReplayResult:
        episode = self.store.get_episode(episode_id)
        if not episode:
            raise ValueError(f"unknown episode_id: {episode_id}")
        events = self.store.get_input_events(episode_id)
        summary = self.input_replayer.replay(
            events=events,
            dry_run=dry_run,
            speed=speed,
            start_delay=start_delay,
        )
        return ReplayResult(
            episode_id=episode_id,
            dry_run=dry_run,
            event_count=len(events),
            summary=summary,
        )
