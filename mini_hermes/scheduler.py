from __future__ import annotations

from dataclasses import dataclass

from mini_hermes.agent import MiniHermesAgent, RunResult
from mini_hermes.store import MiniHermesStore


@dataclass(frozen=True)
class ScheduleRun:
    schedule_id: str
    name: str
    result: RunResult


class MiniHermesScheduler:
    def __init__(self, store: MiniHermesStore | None = None) -> None:
        self.store = store or MiniHermesStore()

    def add_interval_job(self, name: str, task: str, every_minutes: float) -> str:
        interval_seconds = max(1, int(every_minutes * 60))
        return self.store.add_schedule(name=name, task=task, interval_seconds=interval_seconds)

    async def run_due(self, agent: MiniHermesAgent | None = None) -> list[ScheduleRun]:
        agent = agent or MiniHermesAgent(store=self.store)
        completed: list[ScheduleRun] = []
        for job in self.store.due_schedules():
            result = await agent.run(str(job["task"]), learn=True)
            self.store.mark_schedule_run(str(job["schedule_id"]), result.run_id)
            completed.append(
                ScheduleRun(
                    schedule_id=str(job["schedule_id"]),
                    name=str(job["name"]),
                    result=result,
                )
            )
        return completed
