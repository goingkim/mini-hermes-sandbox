from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def now_ts() -> float:
    return time.time()


@dataclass(frozen=True)
class Episode:
    episode_id: str
    task: str
    started_at: float
    ended_at: float | None = None
    status: str = "running"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScreenFrame:
    frame_id: str
    episode_id: str
    timestamp: float
    index: int
    image_path: str
    width: int
    height: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InputEvent:
    event_id: str
    episode_id: str
    timestamp: float
    kind: str
    action: str
    x: int | None = None
    y: int | None = None
    button: str = ""
    key_code: int | None = None
    key_name: str = ""
    key_text: str = ""
    modifiers: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UIPrimitiveRecord:
    primitive_id: str
    episode_id: str
    timestamp: float
    index: int
    name: str
    start_timestamp: float
    end_timestamp: float
    frame_id: str = ""
    input_event_ids: list[str] = field(default_factory=list)
    target: dict[str, Any] = field(default_factory=dict)
    value: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentPlan:
    plan_id: str
    episode_id: str
    timestamp: float
    steps: list[str]
    source: str = "manual"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCallRecord:
    tool_call_id: str
    episode_id: str
    timestamp: float
    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any] | str = field(default_factory=dict)
    status: str = "recorded"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ObservationRecord:
    observation_id: str
    episode_id: str
    timestamp: float
    kind: str
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScoreRecord:
    score_id: str
    episode_id: str
    timestamp: float
    score: float
    reason: str
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HumanFeedback:
    feedback_id: str
    episode_id: str
    timestamp: float
    score: float | None
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


def to_json_record(record_type: str, payload: object) -> dict[str, Any]:
    return {
        "type": record_type,
        "timestamp": getattr(payload, "timestamp", getattr(payload, "started_at", now_ts())),
        "payload": asdict(payload),
    }
