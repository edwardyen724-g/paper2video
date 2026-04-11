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


def _split_narration(text: str, max_words: int = 10) -> list[str]:
    """Split a narration string into short chunks suitable for subtitles.

    Each chunk is at most `max_words` words, splitting on sentence boundaries
    first, then on word count within sentences.
    """
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks: list[str] = []
    for sentence in sentences:
        words = sentence.split()
        while words:
            chunk = words[:max_words]
            words = words[max_words:]
            chunks.append(" ".join(chunk))
    return [c for c in chunks if c.strip()]


def build_srt(scenes: list[Scene], durations: list[float]) -> str:
    lines: list[str] = []
    index = 1
    start = 0.0
    for scene, duration in zip(scenes, durations):
        end = start + duration
        chunks = _split_narration(scene.narration.strip())
        if not chunks:
            chunks = [scene.narration.strip()]
        chunk_duration = duration / len(chunks)
        for chunk in chunks:
            chunk_end = min(start + chunk_duration, end)
            lines.extend(
                [
                    str(index),
                    f"{format_srt_timestamp(start)} --> {format_srt_timestamp(chunk_end)}",
                    chunk,
                    "",
                ]
            )
            index += 1
            start = chunk_end
        start = end
    return "\n".join(lines).strip() + "\n"


def write_srt(path: Path, scenes: list[Scene], durations: list[float]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_srt(scenes, durations), encoding="utf-8")
    return path


def burn_subtitles(
    video_path: Path,
    captions_path: Path,
    out_path: Path,
    portrait: bool = False,
) -> Path:
    ffmpeg = _ffmpeg()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    captions_filter = str(captions_path.resolve()).replace("\\", "/").replace(":", "\\:")

    if portrait:
        # Portrait (1080x1920) with reframed layout:
        # Top 200px = title, middle 1080px = animation, bottom 640px = subtitle zone
        # MarginV=200 pushes text 200px up from bottom edge → well inside the 640px zone
        # FontSize=16 is readable on phone without overlapping animation
        style = (
            "FontName=Arial,FontSize=16,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,BorderStyle=1,Outline=1,Shadow=0,"
            "Alignment=2,MarginV=200,MarginL=60,MarginR=60"
        )
    else:
        # Landscape (1920x1080): original style
        style = (
            "FontName=Arial,FontSize=22,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,"
            "Alignment=2,MarginV=120"
        )

    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-vf",
        f"subtitles='{captions_filter}':force_style='{style}'",
        "-c:a",
        "copy",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path
