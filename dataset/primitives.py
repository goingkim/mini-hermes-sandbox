from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dataset.schema import UIPrimitiveRecord, new_id
from dataset.storage import EpisodeStore


UI_PRIMITIVE_VOCABULARY: dict[str, str] = {
    "move_mouse": "Move the pointer toward a UI target.",
    "click": "Click a UI target at screen coordinates.",
    "scroll": "Scroll the current viewport or control.",
    "type_text": "Enter a run of printable text into the focused control.",
    "press_key": "Press a non-text key such as Enter, Tab, Escape, or Backspace.",
    "verify_state": "Inspect the resulting screen state for success or failure.",
}


@dataclass(frozen=True)
class PrimitiveBuildResult:
    episode_id: str
    primitive_count: int
    counts: dict[str, int]


@dataclass(frozen=True)
class PrimitiveExportResult:
    episode_id: str
    output_path: str
    sample_count: int


class UIPrimitiveBuilder:
    def __init__(self, store: EpisodeStore | None = None) -> None:
        self.store = store or EpisodeStore()

    def build(
        self,
        episode_id: str,
        persist: bool = True,
        include_verify_state: bool = True,
        source: str = "heuristic-v1",
    ) -> PrimitiveBuildResult:
        episode = self.store.get_episode(episode_id)
        if not episode:
            raise ValueError(f"unknown episode_id: {episode_id}")

        frames = self.store.get_frames(episode_id)
        events = self.store.get_input_events(episode_id)
        metadata = _json_dict(episode.get("metadata_json"))
        primitives = self._build_from_events(
            episode_id=episode_id,
            events=events,
            frames=frames,
            episode_metadata=metadata,
            source=source,
        )
        if include_verify_state and frames:
            primitives.append(
                self._verify_state_primitive(
                    episode=episode,
                    frames=frames,
                    index=len(primitives),
                    source=source,
                    episode_metadata=metadata,
                )
            )

        if persist:
            self.store.replace_ui_primitives(episode_id, primitives, source=source)

        counts: dict[str, int] = {}
        for primitive in primitives:
            counts[primitive.name] = counts.get(primitive.name, 0) + 1
        return PrimitiveBuildResult(
            episode_id=episode_id,
            primitive_count=len(primitives),
            counts=counts,
        )

    def export_training_jsonl(
        self,
        episode_id: str,
        output_path: str | Path,
        build_if_missing: bool = True,
    ) -> PrimitiveExportResult:
        episode = self.store.get_episode(episode_id)
        if not episode:
            raise ValueError(f"unknown episode_id: {episode_id}")
        primitives = self.store.get_ui_primitives(episode_id)
        if not primitives and build_if_missing:
            self.build(episode_id, persist=True)
            primitives = self.store.get_ui_primitives(episode_id)

        frames = {str(frame.get("frame_id")): frame for frame in self.store.get_frames(episode_id)}
        latest_score = self.store.get_latest_score(episode_id)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as handle:
            for primitive in primitives:
                frame = frames.get(str(primitive.get("frame_id") or ""))
                target = _json_dict(primitive.get("target_json"))
                value = _json_dict(primitive.get("value_json"))
                sample = {
                    "sample_type": "ui_primitive",
                    "episode_id": episode_id,
                    "task": episode.get("task", ""),
                    "primitive_index": int(primitive.get("primitive_index") or 0),
                    "primitive": primitive.get("name", ""),
                    "instruction": _primitive_instruction(
                        task=str(episode.get("task", "")),
                        primitive_name=str(primitive.get("name", "")),
                        target=target,
                        value=value,
                    ),
                    "frame_id": primitive.get("frame_id") or "",
                    "frame_path": frame.get("image_path", "") if frame else "",
                    "start_timestamp": primitive.get("start_timestamp"),
                    "end_timestamp": primitive.get("end_timestamp"),
                    "input_event_ids": _json_list(primitive.get("input_event_ids_json")),
                    "target": target,
                    "value": value,
                    "reward": _score_payload(latest_score),
                    "metadata": _json_dict(primitive.get("metadata_json")),
                }
                handle.write(json.dumps(sample, ensure_ascii=False, sort_keys=True) + "\n")
        return PrimitiveExportResult(
            episode_id=episode_id,
            output_path=str(output.resolve()),
            sample_count=len(primitives),
        )

    def _build_from_events(
        self,
        episode_id: str,
        events: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        episode_metadata: dict[str, Any],
        source: str,
    ) -> list[UIPrimitiveRecord]:
        primitives: list[UIPrimitiveRecord] = []
        sorted_events = sorted(events, key=lambda item: float(item.get("timestamp") or 0.0))
        i = 0
        while i < len(sorted_events):
            event = sorted_events[i]
            kind = str(event.get("kind") or "")
            action = str(event.get("action") or "")
            if kind == "mouse" and action == "move":
                primitive, i = self._consume_move_run(
                    episode_id=episode_id,
                    events=sorted_events,
                    frames=frames,
                    start_index=i,
                    primitive_index=len(primitives),
                    source=source,
                    episode_metadata=episode_metadata,
                )
                primitives.append(primitive)
                continue
            if kind == "mouse" and action.endswith("_down"):
                primitive, i = self._consume_click(
                    episode_id=episode_id,
                    events=sorted_events,
                    frames=frames,
                    start_index=i,
                    primitive_index=len(primitives),
                    source=source,
                    episode_metadata=episode_metadata,
                )
                primitives.append(primitive)
                continue
            if kind == "mouse" and action == "wheel":
                primitive, i = self._consume_scroll_run(
                    episode_id=episode_id,
                    events=sorted_events,
                    frames=frames,
                    start_index=i,
                    primitive_index=len(primitives),
                    source=source,
                    episode_metadata=episode_metadata,
                )
                primitives.append(primitive)
                continue
            if kind == "keyboard" and action == "key_down" and _is_text_key(event):
                primitive, i = self._consume_text_run(
                    episode_id=episode_id,
                    events=sorted_events,
                    frames=frames,
                    start_index=i,
                    primitive_index=len(primitives),
                    source=source,
                    episode_metadata=episode_metadata,
                )
                primitives.append(primitive)
                continue
            if kind == "keyboard" and action == "key_down":
                primitives.append(
                    self._press_key_primitive(
                        episode_id=episode_id,
                        event=event,
                        frames=frames,
                        index=len(primitives),
                        source=source,
                        episode_metadata=episode_metadata,
                    )
                )
            i += 1
        return primitives

    def _consume_move_run(
        self,
        episode_id: str,
        events: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        start_index: int,
        primitive_index: int,
        source: str,
        episode_metadata: dict[str, Any],
    ) -> tuple[UIPrimitiveRecord, int]:
        consumed = [events[start_index]]
        i = start_index + 1
        while i < len(events) and str(events[i].get("kind")) == "mouse" and str(events[i].get("action")) == "move":
            if float(events[i].get("timestamp") or 0.0) - float(consumed[-1].get("timestamp") or 0.0) > 0.35:
                break
            consumed.append(events[i])
            i += 1
        first = consumed[0]
        last = consumed[-1]
        start_ts = float(first.get("timestamp") or 0.0)
        end_ts = float(last.get("timestamp") or start_ts)
        frame = _frame_at_or_before(frames, start_ts)
        target = _point_target(last, frame)
        target.update(
            {
                "from_x": first.get("x"),
                "from_y": first.get("y"),
                "to_x": last.get("x"),
                "to_y": last.get("y"),
            }
        )
        return (
            _primitive(
                episode_id=episode_id,
                index=primitive_index,
                name="move_mouse",
                start_ts=start_ts,
                end_ts=end_ts,
                frame=frame,
                input_events=consumed,
                target=target,
                value={"point_count": len(consumed)},
                source=source,
                confidence=0.75,
                episode_metadata=episode_metadata,
            ),
            i,
        )

    def _consume_click(
        self,
        episode_id: str,
        events: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        start_index: int,
        primitive_index: int,
        source: str,
        episode_metadata: dict[str, Any],
    ) -> tuple[UIPrimitiveRecord, int]:
        down = events[start_index]
        button = str(down.get("button") or "").replace("_down", "")
        matching_up = f"{button}_up" if button else ""
        end_index = start_index
        for j in range(start_index + 1, min(len(events), start_index + 8)):
            candidate = events[j]
            if float(candidate.get("timestamp") or 0.0) - float(down.get("timestamp") or 0.0) > 0.8:
                break
            if (
                str(candidate.get("kind")) == "mouse"
                and str(candidate.get("action")) == matching_up
                and str(candidate.get("button") or "") == button
            ):
                end_index = j
                break
        consumed = [down] if end_index == start_index else [down, events[end_index]]
        start_ts = float(down.get("timestamp") or 0.0)
        end_ts = float(consumed[-1].get("timestamp") or start_ts)
        frame = _frame_at_or_before(frames, start_ts)
        target = _point_target(down, frame)
        target["button"] = button
        return (
            _primitive(
                episode_id=episode_id,
                index=primitive_index,
                name="click",
                start_ts=start_ts,
                end_ts=end_ts,
                frame=frame,
                input_events=consumed,
                target=target,
                value={"click_type": "single", "button": button},
                source=source,
                confidence=0.9 if len(consumed) == 2 else 0.55,
                episode_metadata=episode_metadata,
            ),
            end_index + 1,
        )

    def _consume_scroll_run(
        self,
        episode_id: str,
        events: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        start_index: int,
        primitive_index: int,
        source: str,
        episode_metadata: dict[str, Any],
    ) -> tuple[UIPrimitiveRecord, int]:
        consumed = [events[start_index]]
        i = start_index + 1
        while i < len(events) and str(events[i].get("kind")) == "mouse" and str(events[i].get("action")) == "wheel":
            if float(events[i].get("timestamp") or 0.0) - float(consumed[-1].get("timestamp") or 0.0) > 0.5:
                break
            consumed.append(events[i])
            i += 1
        start_ts = float(consumed[0].get("timestamp") or 0.0)
        end_ts = float(consumed[-1].get("timestamp") or start_ts)
        frame = _frame_at_or_before(frames, start_ts)
        delta = sum(int(_json_dict(item.get("metadata_json")).get("wheel_delta") or 0) for item in consumed)
        target = _point_target(consumed[-1], frame)
        return (
            _primitive(
                episode_id=episode_id,
                index=primitive_index,
                name="scroll",
                start_ts=start_ts,
                end_ts=end_ts,
                frame=frame,
                input_events=consumed,
                target=target,
                value={
                    "wheel_delta": delta,
                    "direction": "up" if delta > 0 else "down" if delta < 0 else "unknown",
                    "event_count": len(consumed),
                },
                source=source,
                confidence=0.85,
                episode_metadata=episode_metadata,
            ),
            i,
        )

    def _consume_text_run(
        self,
        episode_id: str,
        events: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        start_index: int,
        primitive_index: int,
        source: str,
        episode_metadata: dict[str, Any],
    ) -> tuple[UIPrimitiveRecord, int]:
        consumed = [events[start_index]]
        i = start_index + 1
        while i < len(events):
            item = events[i]
            if str(item.get("kind")) == "keyboard" and str(item.get("action")) == "key_up":
                i += 1
                continue
            if not (str(item.get("kind")) == "keyboard" and str(item.get("action")) == "key_down" and _is_text_key(item)):
                break
            if float(item.get("timestamp") or 0.0) - float(consumed[-1].get("timestamp") or 0.0) > 1.0:
                break
            consumed.append(item)
            i += 1
        start_ts = float(consumed[0].get("timestamp") or 0.0)
        end_ts = float(consumed[-1].get("timestamp") or start_ts)
        frame = _frame_at_or_before(frames, start_ts)
        recorded_chars = [str(item.get("key_text") or "") for item in consumed if item.get("key_text")]
        text_recorded = len(recorded_chars) == len(consumed)
        value = {
            "text": "".join(recorded_chars) if text_recorded else "",
            "text_length": len(consumed),
            "text_recorded": text_recorded,
        }
        return (
            _primitive(
                episode_id=episode_id,
                index=primitive_index,
                name="type_text",
                start_ts=start_ts,
                end_ts=end_ts,
                frame=frame,
                input_events=consumed,
                target={},
                value=value,
                source=source,
                confidence=0.8,
                episode_metadata=episode_metadata,
            ),
            i,
        )

    def _press_key_primitive(
        self,
        episode_id: str,
        event: dict[str, Any],
        frames: list[dict[str, Any]],
        index: int,
        source: str,
        episode_metadata: dict[str, Any],
    ) -> UIPrimitiveRecord:
        timestamp = float(event.get("timestamp") or 0.0)
        frame = _frame_at_or_before(frames, timestamp)
        return _primitive(
            episode_id=episode_id,
            index=index,
            name="press_key",
            start_ts=timestamp,
            end_ts=timestamp,
            frame=frame,
            input_events=[event],
            target={},
            value={
                "key_name": event.get("key_name") or "",
                "key_code": event.get("key_code"),
                "modifiers": _json_list(event.get("modifiers_json")),
            },
            source=source,
            confidence=0.85,
            episode_metadata=episode_metadata,
        )

    def _verify_state_primitive(
        self,
        episode: dict[str, Any],
        frames: list[dict[str, Any]],
        index: int,
        source: str,
        episode_metadata: dict[str, Any],
    ) -> UIPrimitiveRecord:
        frame = frames[-1]
        timestamp = float(episode.get("ended_at") or frame.get("timestamp") or 0.0)
        return _primitive(
            episode_id=str(episode["episode_id"]),
            index=index,
            name="verify_state",
            start_ts=timestamp,
            end_ts=timestamp,
            frame=frame,
            input_events=[],
            target={},
            value={"episode_status": episode.get("status", "")},
            source=source,
            confidence=0.45,
            episode_metadata=episode_metadata,
        )


def _primitive(
    episode_id: str,
    index: int,
    name: str,
    start_ts: float,
    end_ts: float,
    frame: dict[str, Any] | None,
    input_events: list[dict[str, Any]],
    target: dict[str, Any],
    value: dict[str, Any],
    source: str,
    confidence: float,
    episode_metadata: dict[str, Any],
) -> UIPrimitiveRecord:
    metadata: dict[str, Any] = {
        "source": source,
        "confidence": confidence,
        "vocabulary": "ui-primitive-v1",
    }
    if episode_metadata.get("skill_name"):
        metadata["skill_name"] = episode_metadata["skill_name"]
    if episode_metadata.get("expected_ui_primitives"):
        metadata["expected_ui_primitives"] = episode_metadata["expected_ui_primitives"]
    return UIPrimitiveRecord(
        primitive_id=new_id("primitive"),
        episode_id=episode_id,
        timestamp=start_ts,
        index=index,
        name=name,
        start_timestamp=start_ts,
        end_timestamp=end_ts,
        frame_id=str(frame.get("frame_id") or "") if frame else "",
        input_event_ids=[str(item.get("event_id")) for item in input_events if item.get("event_id")],
        target=target,
        value=value,
        metadata=metadata,
    )


def _frame_at_or_before(frames: list[dict[str, Any]], timestamp: float) -> dict[str, Any] | None:
    if not frames:
        return None
    selected = frames[0]
    for frame in frames:
        if float(frame.get("timestamp") or 0.0) <= timestamp:
            selected = frame
        else:
            break
    return selected


def _point_target(event: dict[str, Any], frame: dict[str, Any] | None) -> dict[str, Any]:
    x = event.get("x")
    y = event.get("y")
    target: dict[str, Any] = {"x": x, "y": y}
    if frame and x is not None and y is not None:
        width = max(1, int(frame.get("width") or 1))
        height = max(1, int(frame.get("height") or 1))
        target["normalized_x"] = float(x) / width
        target["normalized_y"] = float(y) / height
    return target


def _is_text_key(event: dict[str, Any]) -> bool:
    modifiers = set(_json_list(event.get("modifiers_json")))
    if modifiers.intersection({"ctrl", "alt", "win"}):
        return False
    if event.get("key_text"):
        return True
    key_name = str(event.get("key_name") or "")
    return len(key_name) == 1 or key_name == "SPACE"


def _primitive_instruction(
    task: str,
    primitive_name: str,
    target: dict[str, Any],
    value: dict[str, Any],
) -> str:
    if primitive_name == "click":
        return f"{task} | click {target.get('button', 'left')} at x={target.get('x')} y={target.get('y')}"
    if primitive_name == "move_mouse":
        return f"{task} | move pointer to x={target.get('to_x')} y={target.get('to_y')}"
    if primitive_name == "scroll":
        return f"{task} | scroll {value.get('direction', 'unknown')}"
    if primitive_name == "type_text":
        return f"{task} | type text_length={value.get('text_length', 0)} into the focused control"
    if primitive_name == "press_key":
        return f"{task} | press key {value.get('key_name') or value.get('key_code')}"
    if primitive_name == "verify_state":
        return f"{task} | verify the final screen state"
    return f"{task} | perform {primitive_name}"


def _score_payload(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {"score": None, "reason": "", "metrics": {}}
    return {
        "score": row.get("score"),
        "reason": row.get("reason", ""),
        "metrics": _json_dict(row.get("metrics_json")),
    }


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


def _json_list(value: object) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []
