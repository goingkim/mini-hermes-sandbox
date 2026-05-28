from __future__ import annotations

from pathlib import Path

from mini_hermes.interaction.schema import ScreenFrame, new_id, now_ts

try:
    from PIL import ImageGrab
except Exception:
    ImageGrab = None


class ScreenCapture:
    def __init__(self, frame_dir: str | Path) -> None:
        self.frame_dir = Path(frame_dir)
        self.frame_dir.mkdir(parents=True, exist_ok=True)

    def capture(self, episode_id: str, index: int) -> ScreenFrame:
        if ImageGrab is None:
            raise RuntimeError("PIL.ImageGrab is unavailable. Install pillow to capture the screen.")

        image = ImageGrab.grab()
        timestamp = now_ts()
        filename = f"{index:06d}_{int(timestamp * 1000)}.png"
        path = self.frame_dir / filename
        image.save(path)
        return ScreenFrame(
            frame_id=new_id("frame"),
            episode_id=episode_id,
            timestamp=timestamp,
            index=index,
            image_path=str(path.resolve()),
            width=int(image.size[0]),
            height=int(image.size[1]),
            metadata={},
        )
