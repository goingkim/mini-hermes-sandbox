from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mini_hermes.interaction.schema import (
    AgentPlan,
    Episode,
    HumanFeedback,
    InputEvent,
    ObservationRecord,
    ScoreRecord,
    ScreenFrame,
    ToolCallRecord,
    new_id,
    now_ts,
    to_json_record,
)
from mini_hermes.privacy import redact_obj, redact_text


class EpisodeStore:
    def __init__(self, root: str | Path = "agent_runs/mini_hermes/episodes") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "episodes.db"
        self._init_db()

    def create_episode(self, task: str, metadata: dict[str, Any] | None = None) -> Episode:
        episode = Episode(
            episode_id=new_id("episode"),
            task=redact_text(task),
            started_at=now_ts(),
            metadata=redact_obj(metadata or {}),
        )
        episode_dir = self.episode_dir(episode.episode_id)
        episode_dir.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.execute(
                """
                insert into episodes (
                    episode_id, task, started_at, ended_at, status, metadata_json, jsonl_path
                )
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode.episode_id,
                    episode.task,
                    episode.started_at,
                    None,
                    episode.status,
                    json.dumps(episode.metadata, ensure_ascii=False, sort_keys=True),
                    str(self.jsonl_path(episode.episode_id)),
                ),
            )
            conn.commit()
        self._append_jsonl(episode.episode_id, "episode_started", episode)
        return episode

    def finish_episode(
        self,
        episode_id: str,
        status: str = "completed",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        ended_at = now_ts()
        existing = self.get_episode(episode_id) or {}
        merged_metadata = _json_dict(existing.get("metadata_json"))
        merged_metadata.update(redact_obj(metadata or {}))
        with closing(self._connect()) as conn:
            conn.execute(
                """
                update episodes
                set ended_at = ?,
                    status = ?,
                    metadata_json = ?
                where episode_id = ?
                """,
                (
                    ended_at,
                    redact_text(status),
                    json.dumps(merged_metadata, ensure_ascii=False, sort_keys=True),
                    episode_id,
                ),
            )
            conn.commit()
        self._append_jsonl(
            episode_id,
            "episode_finished",
            {
                "episode_id": episode_id,
                "timestamp": ended_at,
                "status": status,
                "metadata": redact_obj(metadata or {}),
            },
        )

    def add_frame(self, frame: ScreenFrame) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                insert into frames (
                    frame_id, episode_id, timestamp, frame_index, image_path,
                    width, height, metadata_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    frame.frame_id,
                    frame.episode_id,
                    frame.timestamp,
                    frame.index,
                    redact_text(frame.image_path),
                    frame.width,
                    frame.height,
                    json.dumps(redact_obj(frame.metadata), ensure_ascii=False, sort_keys=True),
                ),
            )
            conn.commit()
        self._append_jsonl(frame.episode_id, "screen_frame", frame)

    def add_input_event(self, event: InputEvent) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                insert into input_events (
                    event_id, episode_id, timestamp, kind, action, x, y, button,
                    key_code, key_name, key_text, modifiers_json, metadata_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.episode_id,
                    event.timestamp,
                    event.kind,
                    event.action,
                    event.x,
                    event.y,
                    event.button,
                    event.key_code,
                    event.key_name,
                    redact_text(event.key_text),
                    json.dumps(redact_obj(event.modifiers), ensure_ascii=False),
                    json.dumps(redact_obj(event.metadata), ensure_ascii=False, sort_keys=True),
                ),
            )
            conn.commit()
        self._append_jsonl(event.episode_id, "input_event", event)

    def add_agent_plan(
        self,
        episode_id: str,
        steps: list[str],
        source: str = "manual",
        metadata: dict[str, Any] | None = None,
    ) -> AgentPlan:
        record = AgentPlan(
            plan_id=new_id("plan"),
            episode_id=episode_id,
            timestamp=now_ts(),
            steps=[redact_text(step) for step in steps],
            source=redact_text(source),
            metadata=redact_obj(metadata or {}),
        )
        with closing(self._connect()) as conn:
            conn.execute(
                """
                insert into agent_plans (
                    plan_id, episode_id, timestamp, steps_json, source, metadata_json
                )
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.plan_id,
                    record.episode_id,
                    record.timestamp,
                    json.dumps(record.steps, ensure_ascii=False),
                    record.source,
                    json.dumps(record.metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
            conn.commit()
        self._append_jsonl(episode_id, "agent_plan", record)
        return record

    def add_tool_call(
        self,
        episode_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any] | str = "",
        status: str = "recorded",
        metadata: dict[str, Any] | None = None,
    ) -> ToolCallRecord:
        record = ToolCallRecord(
            tool_call_id=new_id("tool"),
            episode_id=episode_id,
            timestamp=now_ts(),
            tool_name=redact_text(tool_name),
            arguments=redact_obj(arguments),
            result=redact_obj(result),
            status=redact_text(status),
            metadata=redact_obj(metadata or {}),
        )
        with closing(self._connect()) as conn:
            conn.execute(
                """
                insert into tool_calls (
                    tool_call_id, episode_id, timestamp, tool_name,
                    arguments_json, result_json, status, metadata_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.tool_call_id,
                    record.episode_id,
                    record.timestamp,
                    record.tool_name,
                    json.dumps(record.arguments, ensure_ascii=False, sort_keys=True),
                    json.dumps(record.result, ensure_ascii=False, sort_keys=True)
                    if not isinstance(record.result, str)
                    else redact_text(record.result),
                    record.status,
                    json.dumps(record.metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
            conn.commit()
        self._append_jsonl(episode_id, "tool_call", record)
        return record

    def add_observation(
        self,
        episode_id: str,
        kind: str,
        text: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ObservationRecord:
        record = ObservationRecord(
            observation_id=new_id("observation"),
            episode_id=episode_id,
            timestamp=now_ts(),
            kind=redact_text(kind),
            text=redact_text(text),
            metadata=redact_obj(metadata or {}),
        )
        with closing(self._connect()) as conn:
            conn.execute(
                """
                insert into observations (
                    observation_id, episode_id, timestamp, kind, text, metadata_json
                )
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.observation_id,
                    record.episode_id,
                    record.timestamp,
                    record.kind,
                    record.text,
                    json.dumps(record.metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
            conn.commit()
        self._append_jsonl(episode_id, "observation", record)
        return record

    def add_score(
        self,
        episode_id: str,
        score: float,
        reason: str,
        metrics: dict[str, Any] | None = None,
    ) -> ScoreRecord:
        record = ScoreRecord(
            score_id=new_id("score"),
            episode_id=episode_id,
            timestamp=now_ts(),
            score=max(0.0, min(1.0, float(score))),
            reason=redact_text(reason),
            metrics=redact_obj(metrics or {}),
        )
        with closing(self._connect()) as conn:
            conn.execute(
                """
                insert into scores (
                    score_id, episode_id, timestamp, score, reason, metrics_json
                )
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.score_id,
                    record.episode_id,
                    record.timestamp,
                    record.score,
                    record.reason,
                    json.dumps(record.metrics, ensure_ascii=False, sort_keys=True),
                ),
            )
            conn.commit()
        self._append_jsonl(episode_id, "score", record)
        return record

    def add_human_feedback(
        self,
        episode_id: str,
        text: str,
        score: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> HumanFeedback:
        bounded_score = None if score is None else max(0.0, min(1.0, float(score)))
        record = HumanFeedback(
            feedback_id=new_id("feedback"),
            episode_id=episode_id,
            timestamp=now_ts(),
            score=bounded_score,
            text=redact_text(text),
            metadata=redact_obj(metadata or {}),
        )
        with closing(self._connect()) as conn:
            conn.execute(
                """
                insert into human_feedback (
                    feedback_id, episode_id, timestamp, score, text, metadata_json
                )
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.feedback_id,
                    record.episode_id,
                    record.timestamp,
                    record.score,
                    record.text,
                    json.dumps(record.metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
            conn.commit()
        self._append_jsonl(episode_id, "human_feedback", record)
        return record

    def list_episodes(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._fetch_dicts(
            "select * from episodes order by started_at desc limit ?",
            (limit,),
        )

    def get_episode(self, episode_id: str) -> dict[str, Any] | None:
        return self._fetch_one("select * from episodes where episode_id = ?", (episode_id,))

    def get_frames(self, episode_id: str) -> list[dict[str, Any]]:
        return self._fetch_dicts(
            "select * from frames where episode_id = ? order by frame_index asc",
            (episode_id,),
        )

    def get_input_events(self, episode_id: str) -> list[dict[str, Any]]:
        return self._fetch_dicts(
            "select * from input_events where episode_id = ? order by timestamp asc",
            (episode_id,),
        )

    def get_tool_calls(self, episode_id: str) -> list[dict[str, Any]]:
        return self._fetch_dicts(
            "select * from tool_calls where episode_id = ? order by timestamp asc",
            (episode_id,),
        )

    def get_observations(self, episode_id: str) -> list[dict[str, Any]]:
        return self._fetch_dicts(
            "select * from observations where episode_id = ? order by timestamp asc",
            (episode_id,),
        )

    def get_latest_score(self, episode_id: str) -> dict[str, Any] | None:
        return self._fetch_one(
            "select * from scores where episode_id = ? order by timestamp desc limit 1",
            (episode_id,),
        )

    def export_episode_jsonl(self, episode_id: str, output_path: str | Path) -> Path:
        source = self.jsonl_path(episode_id)
        if not source.exists():
            raise FileNotFoundError(f"episode JSONL not found: {source}")
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, output)
        return output

    def episode_dir(self, episode_id: str) -> Path:
        return self.root / episode_id

    def frame_dir(self, episode_id: str) -> Path:
        return self.episode_dir(episode_id) / "frames"

    def jsonl_path(self, episode_id: str) -> Path:
        return self.episode_dir(episode_id) / "episode.jsonl"

    def _append_jsonl(self, episode_id: str, record_type: str, payload: object) -> None:
        path = self.jsonl_path(episode_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, dict):
            record = {
                "type": record_type,
                "timestamp": payload.get("timestamp", now_ts()),
                "payload": redact_obj(payload),
            }
        else:
            record = to_json_record(record_type, payload)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def _fetch_one(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute(query, params).fetchone()
        return dict(row) if row else None

    def _fetch_dicts(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                create table if not exists episodes (
                    episode_id text primary key,
                    task text not null,
                    started_at real not null,
                    ended_at real,
                    status text not null,
                    metadata_json text not null,
                    jsonl_path text not null
                );

                create table if not exists frames (
                    frame_id text primary key,
                    episode_id text not null,
                    timestamp real not null,
                    frame_index integer not null,
                    image_path text not null,
                    width integer not null,
                    height integer not null,
                    metadata_json text not null
                );

                create table if not exists input_events (
                    event_id text primary key,
                    episode_id text not null,
                    timestamp real not null,
                    kind text not null,
                    action text not null,
                    x integer,
                    y integer,
                    button text,
                    key_code integer,
                    key_name text,
                    key_text text,
                    modifiers_json text,
                    metadata_json text not null
                );

                create table if not exists agent_plans (
                    plan_id text primary key,
                    episode_id text not null,
                    timestamp real not null,
                    steps_json text not null,
                    source text not null,
                    metadata_json text not null
                );

                create table if not exists tool_calls (
                    tool_call_id text primary key,
                    episode_id text not null,
                    timestamp real not null,
                    tool_name text not null,
                    arguments_json text not null,
                    result_json text,
                    status text not null,
                    metadata_json text not null
                );

                create table if not exists observations (
                    observation_id text primary key,
                    episode_id text not null,
                    timestamp real not null,
                    kind text not null,
                    text text,
                    metadata_json text not null
                );

                create table if not exists scores (
                    score_id text primary key,
                    episode_id text not null,
                    timestamp real not null,
                    score real not null,
                    reason text not null,
                    metrics_json text not null
                );

                create table if not exists human_feedback (
                    feedback_id text primary key,
                    episode_id text not null,
                    timestamp real not null,
                    score real,
                    text text not null,
                    metadata_json text not null
                );

                create index if not exists idx_episode_frames on frames(episode_id, frame_index);
                create index if not exists idx_episode_input_events on input_events(episode_id, timestamp);
                create index if not exists idx_episode_tool_calls on tool_calls(episode_id, timestamp);
                create index if not exists idx_episode_scores on scores(episode_id, timestamp);
                """
            )
            conn.commit()


def _json_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
