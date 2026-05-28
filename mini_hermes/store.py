from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from mini_hermes.privacy import redact_obj, redact_text


class MiniHermesStore:
    def __init__(self, db_path: str | Path = "agent_runs/mini_hermes/mini_hermes.db") -> None:
        self.db_path = Path(db_path)
        self.root = self.db_path.parent
        self.root.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def start_run(self, task: str, provider: str, model: str) -> str:
        run_id = str(uuid.uuid4())
        with closing(self._connect()) as conn:
            conn.execute(
                """
                insert into runs (
                    run_id, task, provider, model, plan_json, started_at, status
                )
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    redact_text(task),
                    provider,
                    model,
                    "[]",
                    _now(),
                    "running",
                ),
            )
            conn.commit()
        return run_id

    def finish_run(
        self,
        run_id: str,
        status: str,
        final_answer: str = "",
        score: float | None = None,
        score_reason: str = "",
        error: str = "",
    ) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                update runs
                set ended_at = ?,
                    status = ?,
                    final_answer = ?,
                    score = ?,
                    score_reason = ?,
                    error = ?
                where run_id = ?
                """,
                (
                    _now(),
                    status,
                    redact_text(final_answer),
                    score,
                    redact_text(score_reason),
                    redact_text(error),
                    run_id,
                ),
            )
            conn.commit()

    def add_step(
        self,
        run_id: str,
        step_index: int,
        tool_name: str,
        arguments: dict[str, Any],
        before_observation_id: str = "",
    ) -> int:
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                insert into steps (
                    run_id, step_index, tool_name, arguments_json, started_at,
                    status, before_observation_id
                )
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    step_index,
                    tool_name,
                    json.dumps(redact_obj(arguments), ensure_ascii=False, sort_keys=True),
                    _now(),
                    "running",
                    before_observation_id,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def finish_step(
        self,
        step_id: int,
        status: str,
        result: dict[str, Any] | str,
        error: str = "",
        after_observation_id: str = "",
    ) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                update steps
                set ended_at = ?,
                    status = ?,
                    result_json = ?,
                    error = ?,
                    after_observation_id = ?
                where step_id = ?
                """,
                (
                    _now(),
                    status,
                    json.dumps(redact_obj(result), ensure_ascii=False, sort_keys=True)
                    if not isinstance(result, str)
                    else redact_text(result),
                    redact_text(error),
                    after_observation_id,
                    step_id,
                ),
            )
            conn.commit()

    def add_observation(
        self,
        run_id: str,
        kind: str,
        note: str = "",
        action_label: str = "",
        image_path: str = "",
        metadata: dict[str, Any] | None = None,
        step_id: int | None = None,
    ) -> str:
        observation_id = str(uuid.uuid4())
        with closing(self._connect()) as conn:
            conn.execute(
                """
                insert into observations (
                    observation_id, run_id, step_id, created_at, kind, note,
                    action_label, image_path, metadata_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_id,
                    run_id,
                    step_id,
                    _now(),
                    kind,
                    redact_text(note),
                    redact_text(action_label),
                    redact_text(image_path),
                    json.dumps(redact_obj(metadata or {}), ensure_ascii=False, sort_keys=True),
                ),
            )
            conn.commit()
        return observation_id

    def add_memory(
        self,
        text: str,
        kind: str = "note",
        tags: str = "",
        source_run_id: str = "",
        score: float = 0.0,
    ) -> str:
        memory_id = str(uuid.uuid4())
        with closing(self._connect()) as conn:
            conn.execute(
                """
                insert into memories (
                    memory_id, created_at, kind, text, tags, source_run_id, score
                )
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    _now(),
                    redact_text(kind),
                    redact_text(text),
                    redact_text(tags),
                    source_run_id,
                    score,
                ),
            )
            conn.commit()
        return memory_id

    def search_memories(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        rows = self._fetch_dicts("select * from memories order by created_at desc limit 200")
        return _rank_rows(rows, query, ("text", "tags", "kind"), limit)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self._fetch_one("select * from runs where run_id = ?", (run_id,))

    def get_steps(self, run_id: str) -> list[dict[str, Any]]:
        return self._fetch_dicts(
            "select * from steps where run_id = ? order by step_index, step_id",
            (run_id,),
        )

    def get_observations(self, run_id: str) -> list[dict[str, Any]]:
        return self._fetch_dicts(
            "select * from observations where run_id = ? order by created_at, observation_id",
            (run_id,),
        )

    def rate_run(self, run_id: str, score: float, reason: str) -> None:
        score = max(0.0, min(1.0, float(score)))
        with closing(self._connect()) as conn:
            conn.execute(
                """
                update runs
                set score = ?,
                    score_reason = ?
                where run_id = ?
                """,
                (score, f"user: {redact_text(reason)}", run_id),
            )
            conn.commit()
        run = self.get_run(run_id)
        if run:
            self.add_memory(
                text=f"User rated run {run_id} as {score:.2f}. Task: {run['task']}. Reason: {redact_text(reason)}",
                kind="feedback",
                tags="rating,user-feedback",
                source_run_id=run_id,
                score=score,
            )

    def add_schedule(self, name: str, task: str, interval_seconds: int) -> str:
        schedule_id = str(uuid.uuid4())
        next_run_at = (datetime.now() + timedelta(seconds=interval_seconds)).isoformat(timespec="seconds")
        with closing(self._connect()) as conn:
            conn.execute(
                """
                insert into schedules (
                    schedule_id, name, task, interval_seconds, next_run_at,
                    enabled, created_at
                )
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    schedule_id,
                    redact_text(name),
                    redact_text(task),
                    interval_seconds,
                    next_run_at,
                    1,
                    _now(),
                ),
            )
            conn.commit()
        return schedule_id

    def due_schedules(self) -> list[dict[str, Any]]:
        return self._fetch_dicts(
            """
            select * from schedules
            where enabled = 1 and next_run_at <= ?
            order by next_run_at asc
            """,
            (_now(),),
        )

    def mark_schedule_run(self, schedule_id: str, run_id: str) -> None:
        row = self._fetch_one("select * from schedules where schedule_id = ?", (schedule_id,))
        if not row:
            return
        next_run_at = (
            datetime.now() + timedelta(seconds=int(row["interval_seconds"]))
        ).isoformat(timespec="seconds")
        with closing(self._connect()) as conn:
            conn.execute(
                """
                update schedules
                set last_run_id = ?,
                    next_run_at = ?
                where schedule_id = ?
                """,
                (run_id, next_run_at, schedule_id),
            )
            conn.commit()

    def list_schedules(self) -> list[dict[str, Any]]:
        return self._fetch_dicts("select * from schedules order by next_run_at asc")

    def record_upstream_run(
        self,
        prompt: str,
        provider: str,
        model: str,
        toolsets: tuple[str, ...] | list[str],
        command_display: str,
        returncode: int,
        stdout: str,
        stderr: str,
        elapsed_seconds: float,
        status: str,
    ) -> str:
        upstream_run_id = str(uuid.uuid4())
        with closing(self._connect()) as conn:
            conn.execute(
                """
                insert into upstream_runs (
                    upstream_run_id, created_at, prompt, provider, model,
                    toolsets_json, command_display, returncode, stdout, stderr,
                    elapsed_seconds, status
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    upstream_run_id,
                    _now(),
                    redact_text(prompt),
                    provider,
                    model,
                    json.dumps(redact_obj(list(toolsets)), ensure_ascii=False),
                    redact_text(command_display),
                    int(returncode),
                    redact_text(stdout),
                    redact_text(stderr),
                    float(elapsed_seconds),
                    status,
                ),
            )
            conn.commit()
        return upstream_run_id

    def record_telegram_message(
        self,
        update_id: int | str,
        chat_id_hash: str,
        message_id: int | str,
        username: str,
        text: str,
        status: str,
        run_id: str = "",
        error: str = "",
    ) -> str:
        telegram_event_id = str(uuid.uuid4())
        with closing(self._connect()) as conn:
            conn.execute(
                """
                insert into telegram_messages (
                    telegram_event_id, created_at, update_id, chat_id_hash,
                    message_id, username, text, run_id, status, error
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    telegram_event_id,
                    _now(),
                    str(update_id),
                    redact_text(chat_id_hash),
                    str(message_id),
                    redact_text(username),
                    redact_text(text),
                    run_id,
                    redact_text(status),
                    redact_text(error),
                ),
            )
            conn.commit()
        return telegram_event_id

    def export_trajectories_jsonl(self, output_path: str | Path) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        runs = self._fetch_dicts("select * from runs order by started_at asc")
        with path.open("w", encoding="utf-8") as handle:
            for run in runs:
                steps = self.get_steps(str(run["run_id"]))
                observations = self.get_observations(str(run["run_id"]))
                entry = {
                    "run": run,
                    "steps": steps,
                    "observations": observations,
                    "conversations": _to_training_conversation(run, steps),
                }
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return path

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
                create table if not exists runs (
                    run_id text primary key,
                    task text not null,
                    provider text not null,
                    model text not null,
                    plan_json text not null default '[]',
                    started_at text not null,
                    ended_at text,
                    status text not null,
                    final_answer text,
                    score real,
                    score_reason text,
                    error text
                );

                create table if not exists steps (
                    step_id integer primary key autoincrement,
                    run_id text not null,
                    step_index integer not null,
                    tool_name text not null,
                    arguments_json text not null,
                    result_json text,
                    started_at text not null,
                    ended_at text,
                    status text not null,
                    error text,
                    before_observation_id text,
                    after_observation_id text
                );

                create table if not exists observations (
                    observation_id text primary key,
                    run_id text not null,
                    step_id integer,
                    created_at text not null,
                    kind text not null,
                    note text,
                    action_label text,
                    image_path text,
                    metadata_json text
                );

                create table if not exists memories (
                    memory_id text primary key,
                    created_at text not null,
                    kind text not null,
                    text text not null,
                    tags text,
                    source_run_id text,
                    score real
                );

                create table if not exists schedules (
                    schedule_id text primary key,
                    name text not null,
                    task text not null,
                    interval_seconds integer not null,
                    next_run_at text not null,
                    enabled integer not null,
                    last_run_id text,
                    created_at text not null
                );

                create table if not exists upstream_runs (
                    upstream_run_id text primary key,
                    created_at text not null,
                    prompt text not null,
                    provider text not null,
                    model text not null,
                    toolsets_json text not null,
                    command_display text not null,
                    returncode integer not null,
                    stdout text,
                    stderr text,
                    elapsed_seconds real not null,
                    status text not null
                );

                create table if not exists telegram_messages (
                    telegram_event_id text primary key,
                    created_at text not null,
                    update_id text not null,
                    chat_id_hash text not null,
                    message_id text,
                    username text,
                    text text,
                    run_id text,
                    status text not null,
                    error text
                );

                create index if not exists idx_steps_run_id on steps(run_id);
                create index if not exists idx_observations_run_id on observations(run_id);
                create index if not exists idx_memories_created_at on memories(created_at);
                create index if not exists idx_runs_score on runs(score);
                create index if not exists idx_upstream_runs_created_at on upstream_runs(created_at);
                create index if not exists idx_telegram_messages_created_at on telegram_messages(created_at);
                create index if not exists idx_telegram_messages_run_id on telegram_messages(run_id);
                """
            )
            conn.commit()


def _rank_rows(
    rows: list[dict[str, Any]],
    query: str,
    fields: tuple[str, ...],
    limit: int,
) -> list[dict[str, Any]]:
    tokens = {token.lower() for token in query.replace("/", " ").replace("\\", " ").split() if token}
    if not tokens:
        return rows[:limit]

    scored: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        haystack = " ".join(str(row.get(field, "")) for field in fields).lower()
        score = sum(1 for token in tokens if token in haystack)
        if score:
            scored.append((score, row))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[:limit]]


def _to_training_conversation(run: dict[str, Any], steps: list[dict[str, Any]]) -> list[dict[str, str]]:
    conversation = [{"from": "human", "value": str(run["task"])}]
    for step in steps:
        conversation.append(
            {
                "from": "assistant",
                "value": f"tool:{step['tool_name']} args:{step['arguments_json']}",
            }
        )
        conversation.append({"from": "tool", "value": str(step.get("result_json") or "")})
    if run.get("final_answer"):
        conversation.append({"from": "assistant", "value": str(run["final_answer"])})
    return conversation


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
