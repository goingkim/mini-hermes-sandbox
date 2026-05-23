from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_tools import (  # noqa: E402
    _create_simple_drawing_png,
    draw_in_paint,
    organize_pictures_by_year,
    undo_photo_organization,
)
from trace_store import TraceStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify local tool behavior without using an LLM.")
    parser.add_argument(
        "--open-paint",
        action="store_true",
        help="Open Microsoft Paint with a generated watermelon image.",
    )
    args = parser.parse_args()

    _verify_photo_organizer()
    _verify_drawing_renderers()
    _verify_trace_store()

    if args.open_paint:
        output_path = ROOT / "agent_runs" / "paint" / "verify_watermelon.png"
        print(draw_in_paint("수박", str(output_path), open_paint=True))

    print("local tool verification passed")


def _verify_photo_organizer() -> None:
    with tempfile.TemporaryDirectory(prefix="agent_verify_photos_") as tmp:
        source = Path(tmp) / "photos"
        nested = source / "nested"
        nested.mkdir(parents=True)

        first = source / "first.jpg"
        second = nested / "second.png"
        _write_test_image(first, (240, 20, 20), 2020)
        _write_test_image(second, (20, 80, 220), 2024)

        result = organize_pictures_by_year(str(source), recursive=True, move_files=True)
        manifest = Path(result.split("Manifest: ", 1)[1])

        _assert((source / "ByYear" / "2020" / "first.jpg").exists(), "2020 image was not moved")
        _assert((source / "ByYear" / "2024" / "second.png").exists(), "2024 image was not moved")
        _assert(not first.exists(), "original 2020 image still exists")
        _assert(not second.exists(), "original 2024 image still exists")

        undo_photo_organization(str(manifest))
        _assert(first.exists(), "2020 image was not restored")
        _assert(second.exists(), "2024 image was not restored")


def _verify_drawing_renderers() -> None:
    with tempfile.TemporaryDirectory(prefix="agent_verify_draw_") as tmp:
        output_dir = Path(tmp)
        apple = output_dir / "apple.png"
        watermelon = output_dir / "watermelon.png"
        fallback = output_dir / "fallback.png"

        _create_simple_drawing_png("애플로고", apple)
        _create_simple_drawing_png("수박", watermelon)
        _create_simple_drawing_png("unknown shape", fallback)

        _assert(_count_pixels(apple, lambda r, g, b: r < 40 and g < 40 and b < 40) > 20_000, "apple render missing dark logo")
        _assert(_count_pixels(watermelon, lambda r, g, b: r > 180 and g < 90 and b < 90) > 10_000, "watermelon render missing red flesh")
        _assert(_count_pixels(watermelon, lambda r, g, b: g > 90 and r < 100 and b < 120) > 20_000, "watermelon render missing green rind")
        _assert(fallback.stat().st_size > 1_000, "fallback drawing file too small")


def _verify_trace_store() -> None:
    with tempfile.TemporaryDirectory(prefix="agent_verify_trace_") as tmp:
        db_path = Path(tmp) / "agent.db"
        store = TraceStore(db_path)
        run_id = store.start_run("test", "test-model", "hello")
        store.finish_run(run_id, final_output="ok", last_agent="Verifier")

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "select status, final_output, last_agent from runs where run_id = ?",
                (run_id,),
            ).fetchone()
        finally:
            conn.close()

        _assert(row == ("success", "ok", "Verifier"), "trace row did not persist correctly")


def _write_test_image(path: Path, color: tuple[int, int, int], year: int) -> None:
    Image.new("RGB", (64, 64), color).save(path)
    timestamp = datetime(year, 6, 1, 12, 0, 0).timestamp()
    os.utime(path, (timestamp, timestamp))


def _count_pixels(path: Path, predicate) -> int:
    with Image.open(path) as image:
        rgb_image = image.convert("RGB")
        get_pixels = getattr(rgb_image, "get_flattened_data", rgb_image.getdata)
        return sum(1 for r, g, b in get_pixels() if predicate(r, g, b))


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    main()
