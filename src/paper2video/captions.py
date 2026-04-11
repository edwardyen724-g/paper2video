from __future__ import annotations

import subprocess
from pathlib import Path

from .assemble import _ffmpeg
from .types import Scene


def format_srt_timestamp(total_seconds: float) -> str:
    millis = max(0, int(round(total_seconds * 1000)))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def build_srt(scenes: list[Scene], durations: list[float]) -> str:
    lines: list[str] = []
    start = 0.0
    for index, (scene, duration) in enumerate(zip(scenes, durations), start=1):
        end = start + duration
        lines.extend(
            [
                str(index),
                f"{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}",
                scene.narration.strip(),
                "",
            ]
        )
        start = end
    return "\n".join(lines).strip() + "\n"


def write_srt(path: Path, scenes: list[Scene], durations: list[float]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_srt(scenes, durations), encoding="utf-8")
    return path


def burn_subtitles(video_path: Path, captions_path: Path, out_path: Path) -> Path:
    ffmpeg = _ffmpeg()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    captions_filter = str(captions_path.resolve()).replace("\\", "/").replace(":", "\\:")
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-vf",
        f"subtitles='{captions_filter}':force_style='FontName=Arial,FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=120'",
        "-c:a",
        "copy",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path
