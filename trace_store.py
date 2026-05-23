from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path


class TraceStore:
    def __init__(self, db_path: str | Path = "agent_runs/agent.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def start_run(self, provider: str, model: str, user_input: str) -> str:
        run_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                insert into runs (
                    run_id, started_at, provider, model, user_input, status
                )
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    datetime.now().isoformat(timespec="seconds"),
                    provider,
                    model,
                    user_input,
                    "running",
                ),
            )
        return run_id

    def finish_run(
        self,
        run_id: str,
        final_output: str = "",
        last_agent: str = "",
        status: str = "success",
        error: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                update runs
                set ended_at = ?,
                    final_output = ?,
                    last_agent = ?,
                    status = ?,
                    error = ?
                where run_id = ?
                """,
                (
                    datetime.now().isoformat(timespec="seconds"),
                    final_output,
                    last_agent,
                    status,
                    error,
                    run_id,
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists runs (
                    run_id text primary key,
                    started_at text not null,
                    ended_at text,
                    provider text not null,
                    model text not null,
                    user_input text not null,
                    final_output text,
                    last_agent text,
                    status text not null,
                    error text
                )
                """
            )
