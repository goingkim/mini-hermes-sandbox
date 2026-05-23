from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
    ".heic",
    ".heif",
}

EXIF_DATE_TAGS = (36867, 36868, 306)


def organize_pictures_by_year(
    source_folder: str = "",
    destination_folder: str = "",
    recursive: bool = True,
    move_files: bool = True,
) -> str:
    """Organize image files into year folders using EXIF date first, then file modified time.

    If source_folder is blank, the user's Windows Pictures folder is used. If destination_folder
    is blank, files are organized under source_folder/ByYear/YYYY. A manifest is always saved so
    the operation can be reviewed or undone later.
    """
    source = Path(source_folder).expanduser() if source_folder else Path.home() / "Pictures"
    if not source.exists() or not source.is_dir():
        return f"Source folder does not exist or is not a directory: {source}"

    destination_root = (
        Path(destination_folder).expanduser()
        if destination_folder
        else source / "ByYear"
    )
    destination_root.mkdir(parents=True, exist_ok=True)

    manifest_dir = Path("agent_runs") / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest_path = manifest_dir / f"photo_organize_{timestamp}.json"

    files = _iter_image_files(source, destination_root, recursive)
    operations: list[dict[str, Any]] = []
    skipped = 0

    for file_path in files:
        try:
            year = _image_year(file_path)
            year_dir = destination_root / str(year)
            year_dir.mkdir(parents=True, exist_ok=True)
            target_path = _unique_path(year_dir / file_path.name)

            if move_files:
                shutil.move(str(file_path), str(target_path))
                action = "move"
            else:
                shutil.copy2(str(file_path), str(target_path))
                action = "copy"

            operations.append(
                {
                    "action": action,
                    "year": year,
                    "source": str(file_path),
                    "target": str(target_path),
                }
            )
        except Exception as exc:
            skipped += 1
            operations.append(
                {
                    "action": "skip",
                    "source": str(file_path),
                    "error": str(exc),
                }
            )

    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_folder": str(source),
        "destination_folder": str(destination_root),
        "recursive": recursive,
        "move_files": move_files,
        "operations": operations,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    completed = len([op for op in operations if op["action"] in {"move", "copy"}])
    action_label = "moved" if move_files else "copied"
    return (
        f"Organized {completed} image(s); skipped {skipped}. "
        f"Files were {action_label} into {destination_root}. "
        f"Manifest: {manifest_path.resolve()}"
    )


def undo_photo_organization(manifest_path: str) -> str:
    """Undo a previous organize_pictures_by_year move operation using its manifest file."""
    manifest_file = Path(manifest_path).expanduser()
    if not manifest_file.exists():
        return f"Manifest does not exist: {manifest_file}"

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    restored = 0
    skipped = 0

    for op in reversed(manifest.get("operations", [])):
        if op.get("action") != "move":
            skipped += 1
            continue

        source = Path(op["source"])
        target = Path(op["target"])
        if not target.exists():
            skipped += 1
            continue

        source.parent.mkdir(parents=True, exist_ok=True)
        restore_path = _unique_path(source)
        shutil.move(str(target), str(restore_path))
        restored += 1

    return f"Restored {restored} image(s); skipped {skipped}. Manifest: {manifest_file.resolve()}"


def draw_in_paint(description: str, save_path: str = "", open_paint: bool = True) -> str:
    """Create a simple image from a description and open it in Microsoft Paint.

    This is a generic Paint tool. It selects a renderer by description and falls
    back to a neutral placeholder for unsupported drawing requests. Leave
    open_paint=True unless the caller explicitly wants file generation only.
    """
    output_path = (
        Path(save_path).expanduser()
        if save_path
        else Path("agent_runs") / "paint" / "drawing.png"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _create_simple_drawing_png(description, output_path)

    if open_paint:
        subprocess.Popen(["mspaint.exe", str(output_path.resolve())])
        return f"Opened Microsoft Paint with generated image: {output_path.resolve()}"

    return f"Generated image without opening Paint: {output_path.resolve()}"


def _iter_image_files(source: Path, destination_root: Path, recursive: bool) -> list[Path]:
    iterator = source.rglob("*") if recursive else source.iterdir()
    files: list[Path] = []
    destination_root_resolved = destination_root.resolve()

    for path in iterator:
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        try:
            path.resolve().relative_to(destination_root_resolved)
            continue
        except ValueError:
            files.append(path)

    return files


def _image_year(file_path: Path) -> int:
    exif_year = _exif_year(file_path)
    if exif_year:
        return exif_year
    return datetime.fromtimestamp(file_path.stat().st_mtime).year


def _exif_year(file_path: Path) -> int | None:
    if file_path.suffix.lower() not in {".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".png"}:
        return None

    try:
        with Image.open(file_path) as image:
            exif = image.getexif()
    except Exception:
        return None

    for tag in EXIF_DATE_TAGS:
        value = exif.get(tag)
        if not value:
            continue
        text = value.decode("utf-8", errors="ignore") if isinstance(value, bytes) else str(value)
        try:
            return datetime.strptime(text[:19], "%Y:%m:%d %H:%M:%S").year
        except ValueError:
            continue
    return None


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    for index in range(1, 10_000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find a free filename for {path}")


def _create_simple_drawing_png(description: str, output_path: Path) -> None:
    normalized = description.lower()
    for keywords, renderer in _drawing_renderers():
        if any(keyword in normalized for keyword in keywords):
            renderer(output_path)
            return

    _create_generic_placeholder_png(output_path)


def _drawing_renderers() -> tuple[tuple[tuple[str, ...], Callable[[Path], None]], ...]:
    return (
        (("apple", "애플"), _create_apple_style_logo_png),
        (("watermelon", "수박"), _create_watermelon_png),
        (("banana", "바나나"), _create_banana_png),
    )


def _create_generic_placeholder_png(output_path: Path) -> None:
    size = 800
    image = Image.new("RGB", (size, size), (250, 252, 248))
    draw = ImageDraw.Draw(image)
    draw.rectangle((90, 90, 710, 710), outline=(60, 68, 76), width=6)
    draw.line((180, 500, 310, 350, 440, 430, 620, 260), fill=(90, 132, 180), width=24)
    draw.line((180, 505, 310, 355, 440, 435, 620, 265), fill=(180, 210, 236), width=10)
    draw.ellipse((145, 470, 215, 540), fill=(245, 185, 70), outline=(80, 65, 45), width=4)
    draw.polygon([(610, 245), (660, 230), (635, 285)], fill=(80, 65, 45))
    image.save(output_path)


def _create_apple_style_logo_png(output_path: Path) -> None:
    size = 800
    image = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)

    draw.ellipse((150, 185, 420, 610), fill=255)
    draw.ellipse((315, 175, 610, 610), fill=255)
    draw.ellipse((225, 330, 535, 700), fill=255)
    draw.ellipse((260, 115, 475, 285), fill=0)
    draw.ellipse((500, 250, 680, 410), fill=0)
    draw.ellipse((245, 590, 530, 760), fill=0)

    logo = Image.new("RGBA", (size, size), (15, 15, 15, 255))
    image.paste(logo, (0, 0), mask)

    leaf = Image.new("RGBA", (220, 140), (0, 0, 0, 0))
    leaf_mask = Image.new("L", (220, 140), 0)
    leaf_draw = ImageDraw.Draw(leaf_mask)
    leaf_draw.ellipse((20, 20, 200, 105), fill=255)
    leaf_logo = Image.new("RGBA", (220, 140), (15, 15, 15, 255))
    leaf.paste(leaf_logo, (0, 0), leaf_mask)
    leaf = leaf.rotate(-28, expand=True, resample=Image.Resampling.BICUBIC)
    image.alpha_composite(leaf, (405, 75))

    image.convert("RGB").save(output_path)


def _create_watermelon_png(output_path: Path) -> None:
    size = 800
    image = Image.new("RGB", (size, size), (250, 252, 248))
    draw = ImageDraw.Draw(image)

    draw.ellipse((110, 130, 690, 710), fill=(38, 143, 72), outline=(18, 78, 42), width=8)
    stripe_color = (17, 100, 52)
    for bbox in (
        (135, 150, 385, 700),
        (245, 140, 555, 710),
        (415, 150, 665, 700),
    ):
        draw.arc(bbox, 70, 290, fill=stripe_color, width=18)

    rind_points = [(175, 620), (625, 620), (400, 255)]
    flesh_points = [(210, 590), (590, 590), (400, 300)]
    draw.polygon(rind_points, fill=(32, 129, 64))
    draw.line((175, 620, 625, 620), fill=(16, 82, 41), width=42)
    draw.line((195, 596, 605, 596), fill=(172, 220, 96), width=16)
    draw.polygon(flesh_points, fill=(224, 48, 55))

    seed_color = (31, 27, 24)
    for x, y in (
        (345, 455),
        (455, 455),
        (300, 530),
        (405, 520),
        (505, 530),
    ):
        draw.ellipse((x - 12, y - 20, x + 12, y + 20), fill=seed_color)

    image.save(output_path)


def _create_banana_png(output_path: Path) -> None:
    size = 800
    image = Image.new("RGB", (size, size), (250, 252, 248))
    draw = ImageDraw.Draw(image)

    outer_curve = [
        (120, 390),
        (190, 505),
        (320, 610),
        (500, 625),
        (675, 500),
    ]
    inner_curve = [
        (185, 355),
        (280, 435),
        (405, 500),
        (545, 480),
        (660, 395),
    ]

    draw.line(outer_curve, fill=(102, 68, 23), width=122, joint="curve")
    draw.line(outer_curve, fill=(246, 198, 48), width=104, joint="curve")
    draw.line(inner_curve, fill=(250, 252, 248), width=92, joint="curve")

    draw.line(outer_curve, fill=(255, 223, 83), width=42, joint="curve")
    draw.line(
        [(160, 410), (245, 505), (360, 565), (510, 570), (635, 485)],
        fill=(255, 238, 128),
        width=12,
        joint="curve",
    )

    draw.ellipse((78, 342, 160, 430), fill=(96, 60, 20))
    draw.ellipse((642, 450, 720, 535), fill=(98, 64, 24))
    draw.ellipse((105, 360, 145, 405), fill=(155, 96, 30))
    draw.ellipse((657, 466, 698, 510), fill=(150, 92, 28))

    image.save(output_path)
