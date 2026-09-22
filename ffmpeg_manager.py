from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

MAX_BYTES = 190 * 1024
MAX_SIDE = 320


def ffmpeg_path() -> Optional[str]:
    return shutil.which("ffmpeg")


def ffprobe_path() -> Optional[str]:
    return shutil.which("ffprobe")


def check_ffmpeg() -> tuple[bool, bool, str]:
    ff = ffmpeg_path()
    fp = ffprobe_path()
    if not ff:
        return False, bool(fp), "ffmpeg is not available in the Android build."
    try:
        result = subprocess.run([ff, "-version"], capture_output=True, text=True, timeout=10)
        first = (result.stdout or result.stderr).splitlines()[0] if (result.stdout or result.stderr) else "ffmpeg found"
    except Exception as exc:
        return True, bool(fp), f"ffmpeg found but could not be queried: {exc}"
    return True, bool(fp), first


def make_jpeg_thumbnail(video_path: Path, output_path: Optional[Path] = None) -> Optional[Path]:
    """Extract a persistent JPEG next to the video using the Android-bundled ffmpeg."""
    ff = ffmpeg_path()
    if not ff or not video_path.exists():
        return None

    output = output_path or video_path.with_name(video_path.stem + ".preview.jpg")
    output.parent.mkdir(parents=True, exist_ok=True)

    # Several timestamps make the result more reliable when the first frames are black.
    for seek in (1.0, 0.25, 0.0):
        for quality in (6, 10, 14, 18, 22, 28):
            output.unlink(missing_ok=True)
            cmd = [
                ff, "-y", "-hide_banner", "-loglevel", "error",
                "-ss", f"{seek:.3f}", "-i", str(video_path),
                "-frames:v", "1",
                "-vf", "scale=min(320\\,iw):-2",
                "-q:v", str(quality), str(output),
            ]
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
            except Exception:
                continue
            if output.exists() and 0 < output.stat().st_size <= MAX_BYTES:
                return output

    output.unlink(missing_ok=True)
    return None
