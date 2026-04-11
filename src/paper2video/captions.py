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


def _split_narration(text: str, max_words: int = 6) -> list[str]:
    """Split a narration string into short chunks suitable for subtitles.

    Each chunk is at most `max_words` words, splitting on sentence boundaries
    first, then on natural pause points (commas, dashes, semicolons),
    then on word count.

    Shorter chunks (6 words default) keep subtitle changes frequent and
    reduce visible timing drift vs the audio.
    """
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks: list[str] = []
    for sentence in sentences:
        # Try splitting on natural pauses first
        parts = re.split(r'(?<=[,;—–])\s+', sentence)
        for part in parts:
            words = part.split()
            while words:
                chunk = words[:max_words]
                words = words[max_words:]
                chunks.append(" ".join(chunk))
    return [c for c in chunks if c.strip()]


def build_srt(scenes: list[Scene], durations: list[float]) -> str:
    """Build SRT with word-count-weighted timing per chunk.

    Each chunk's duration is proportional to its word count relative to
    the scene's total words. This tracks natural speech pacing better
    than even division (longer phrases get more time).

    A 0.1s lead-in offset on each scene makes subtitles appear slightly
    after the audio starts, which feels more synced perceptually.
    """
    lines: list[str] = []
    index = 1
    scene_start = 0.0
    for scene, duration in zip(scenes, durations):
        scene_end = scene_start + duration
        chunks = _split_narration(scene.narration.strip())
        if not chunks:
            chunks = [scene.narration.strip()]

        # Weight by word count
        word_counts = [len(c.split()) for c in chunks]
        total_words = sum(word_counts) or 1
        # Reserve 0.1s lead-in and 0.1s tail
        usable = max(duration - 0.2, 0.5)
        cursor = scene_start + 0.1  # lead-in offset

        for chunk, wc in zip(chunks, word_counts):
            chunk_dur = usable * (wc / total_words)
            chunk_end = min(cursor + chunk_dur, scene_end)
            lines.extend(
                [
                    str(index),
                    f"{format_srt_timestamp(cursor)} --> {format_srt_timestamp(chunk_end)}",
                    chunk,
                    "",
                ]
            )
            index += 1
            cursor = chunk_end

        scene_start = scene_end
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
        # Portrait: use force_style with explicit PlayResY to match our 1920px frame.
        # Without PlayResY, ffmpeg's ASS renderer assumes 288 and scales MarginV
        # proportionally, placing subtitles in the wrong position.
        style = (
            "PlayResX=1080,PlayResY=1920,"
            "FontName=Arial,FontSize=52,Bold=1,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=0,"
            "Alignment=2,MarginV=120,MarginL=60,MarginR=60"
        )
    else:
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
