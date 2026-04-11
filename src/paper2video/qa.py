"""Automated quality assurance for rendered videos.

Runs after assembly, before human review. Catches the classes of bugs
that the lint rules haven't learned yet — cutoffs, overlapping text,
unreadable content, silent audio, bad pacing.

Two tiers:
  1. Programmatic checks (fast, free) — audio levels, frame dimensions,
     subtitle overlap heuristics, duration sanity.
  2. Visual LLM review (slower, costs ~$0.01) — extract frames at scene
     midpoints, ask the LLM if anything looks wrong.

Returns a list of QAIssue objects. If any are severity="error", the pipeline
should auto-retry the bad scenes before sending to Telegram.
"""
from __future__ import annotations
import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .assemble import _ffmpeg
from .llm import LLMClient
from .types import ScriptDoc


@dataclass
class QAIssue:
    severity: Literal["error", "warning"]
    scene_id: int | None  # None = whole-video issue
    category: str  # "audio", "visual", "subtitle", "pacing"
    message: str


@dataclass
class QAResult:
    issues: list[QAIssue] = field(default_factory=list)
    passed: bool = True

    def add(self, issue: QAIssue) -> None:
        self.issues.append(issue)
        if issue.severity == "error":
            self.passed = False

    @property
    def error_scene_ids(self) -> set[int]:
        return {i.scene_id for i in self.issues if i.severity == "error" and i.scene_id is not None}


# ---- Tier 1: Programmatic checks (free, fast) ----

def _check_audio_levels(audio_dir: Path, scene_count: int) -> list[QAIssue]:
    """Check that audio files exist and aren't silent."""
    issues: list[QAIssue] = []
    for i in range(1, scene_count + 1):
        path = audio_dir / f"scene_{i:03d}.wav"
        if not path.exists():
            issues.append(QAIssue("error", i, "audio", f"Audio file missing: {path.name}"))
            continue
        with wave.open(str(path)) as w:
            n_frames = w.getnframes()
            duration = n_frames / w.getframerate()
            if duration < 0.5:
                issues.append(QAIssue("error", i, "audio",
                    f"Audio too short ({duration:.1f}s) — likely FakeTTS or synthesis failure"))
            # Check if audio is all silence (all zeros)
            raw = w.readframes(min(n_frames, w.getframerate()))  # first 1 second
            if raw == b'\x00' * len(raw):
                issues.append(QAIssue("error", i, "audio",
                    f"Audio is silent — FakeTTS output or synthesis failure"))
    return issues


def _check_video_dimensions(video_path: Path, expected_w: int, expected_h: int) -> list[QAIssue]:
    """Verify the assembled video matches expected dimensions."""
    issues: list[QAIssue] = []
    ffmpeg = _ffmpeg()
    res = subprocess.run(
        [ffmpeg, "-i", str(video_path)],
        capture_output=True, text=True,
    )
    # Parse resolution from ffmpeg stderr
    import re
    match = re.search(r'(\d{3,4})x(\d{3,4})', res.stderr)
    if match:
        w, h = int(match.group(1)), int(match.group(2))
        if w != expected_w or h != expected_h:
            issues.append(QAIssue("warning", None, "visual",
                f"Video dimensions {w}x{h} don't match expected {expected_w}x{expected_h}"))
    else:
        issues.append(QAIssue("warning", None, "visual", "Could not parse video dimensions"))
    return issues


def _check_duration_sanity(video_path: Path, expected_min: float, expected_max: float) -> list[QAIssue]:
    """Check total video duration is within expected bounds."""
    issues: list[QAIssue] = []
    ffmpeg = _ffmpeg()
    res = subprocess.run(
        [ffmpeg, "-i", str(video_path)],
        capture_output=True, text=True,
    )
    import re
    match = re.search(r'Duration:\s*(\d+):(\d+):(\d+\.\d+)', res.stderr)
    if match:
        h, m, s = int(match.group(1)), int(match.group(2)), float(match.group(3))
        total = h * 3600 + m * 60 + s
        if total < expected_min:
            issues.append(QAIssue("error", None, "pacing",
                f"Video too short ({total:.1f}s, expected >={expected_min:.0f}s) — scenes may have failed"))
        if total > expected_max:
            issues.append(QAIssue("warning", None, "pacing",
                f"Video too long ({total:.1f}s, expected <={expected_max:.0f}s) — may need tighter pacing"))
    return issues


def _check_subtitle_text_length(captions_path: Path) -> list[QAIssue]:
    """Check that individual subtitle blocks aren't too long (would overlap animation)."""
    issues: list[QAIssue] = []
    if not captions_path or not captions_path.exists():
        return issues
    text = captions_path.read_text(encoding="utf-8")
    blocks = text.strip().split("\n\n")
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            subtitle_text = " ".join(lines[2:])
            word_count = len(subtitle_text.split())
            if word_count > 20:
                issues.append(QAIssue("warning", None, "subtitle",
                    f"Subtitle block too long ({word_count} words): '{subtitle_text[:60]}...' — "
                    f"will overlap animation on small screens"))
    return issues


# ---- Tier 2: Visual LLM review (costs ~$0.01 per scene) ----

def _extract_frame(video_path: Path, timestamp_sec: float, out_path: Path) -> Path | None:
    """Extract a single frame from a video at the given timestamp."""
    ffmpeg = _ffmpeg()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-ss", f"{timestamp_sec:.2f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(out_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0 and out_path.exists():
        return out_path
    return None


def _extract_scene_frames(
    scene_clips: list[Path],
    durations: list[float],
    out_dir: Path,
) -> list[Path]:
    """Extract a midpoint frame from each scene clip."""
    frames: list[Path] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, (clip, dur) in enumerate(zip(scene_clips, durations), start=1):
        midpoint = dur / 2
        frame_path = out_dir / f"qa_frame_{i:03d}.jpg"
        result = _extract_frame(clip, midpoint, frame_path)
        if result:
            frames.append(result)
    return frames


VISUAL_QA_PROMPT = """You are a quality assurance reviewer for auto-generated educational videos.

Look at this frame from scene {scene_id} of a {orientation} video ({width}x{height}).

The narration for this scene is:
"{narration}"

Check for these specific issues:

1. TEXT CUTOFF: Is any text cut off by the edges of the frame? Text running past left/right/top/bottom edges.
2. TEXT OVERLAP: Are any text labels overlapping each other, making them unreadable?
3. UNREADABLE TEXT: Is any text too small, too faint, or obscured to read?
4. EMPTY SCENE: Is the frame mostly empty/black with very little visual content?
5. LAYOUT: Do elements look properly spaced, or are they crammed together or floating randomly?

Respond with JSON only:
{{
  "issues": [
    {{"severity": "error", "category": "visual", "message": "description of the problem"}}
  ]
}}

If the frame looks fine, return: {{"issues": []}}
Only report real, obvious problems. Minor aesthetic preferences are not issues.
"""


def _llm_review_frame(
    frame_path: Path,
    scene_id: int,
    narration: str,
    width: int,
    height: int,
    llm: LLMClient,
) -> list[QAIssue]:
    """Ask the LLM to review a single frame for visual issues."""
    import base64
    orientation = "portrait (vertical, for phones)" if height > width else "landscape"

    # Read and base64-encode the frame
    frame_data = frame_path.read_bytes()
    b64 = base64.b64encode(frame_data).decode("utf-8")

    # Use the LLM's vision capability
    try:
        import anthropic
        # Need to use the raw client for image input
        import os
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        model = os.environ.get("PAPER2VIDEO_MODEL", "claude-haiku-4-5-20251001")

        prompt_text = VISUAL_QA_PROMPT.format(
            scene_id=scene_id,
            orientation=orientation,
            width=width,
            height=height,
            narration=narration[:300],
        )

        msg = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
                    },
                    {"type": "text", "text": prompt_text},
                ],
            }],
        )
        import json
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw.rsplit("```", 1)[0]
        result = json.loads(raw)
        issues = []
        for item in result.get("issues", []):
            issues.append(QAIssue(
                severity=item.get("severity", "warning"),
                scene_id=scene_id,
                category=item.get("category", "visual"),
                message=item.get("message", "unknown issue"),
            ))
        return issues
    except Exception as e:
        return [QAIssue("warning", scene_id, "visual", f"LLM QA review failed: {e}")]


# ---- Public API ----

def run_qa(
    video_path: Path,
    audio_dir: Path,
    script: ScriptDoc,
    expected_w: int,
    expected_h: int,
    captions_path: Path | None = None,
    scene_clips: list[Path] | None = None,
    durations: list[float] | None = None,
    llm: LLMClient | None = None,
    qa_dir: Path | None = None,
    skip_audio_check: bool = False,
    skip_pacing_check: bool = False,
) -> QAResult:
    """Run all QA checks on a rendered video.

    Tier 1 (programmatic) always runs. Tier 2 (visual LLM) runs if
    `llm` and `scene_clips` are provided.
    """
    result = QAResult()

    # Tier 1: Programmatic
    if not skip_audio_check:
        for issue in _check_audio_levels(audio_dir, len(script.scenes)):
            result.add(issue)

    for issue in _check_video_dimensions(video_path, expected_w, expected_h):
        result.add(issue)

    if not skip_pacing_check:
        is_social = expected_h > expected_w
        min_dur = 30 if is_social else 60
        max_dur = 90 if is_social else 360
        for issue in _check_duration_sanity(video_path, min_dur, max_dur):
            result.add(issue)

    if captions_path:
        for issue in _check_subtitle_text_length(captions_path):
            result.add(issue)

    # Tier 2: Visual LLM review
    if llm and scene_clips and durations and qa_dir:
        frames = _extract_scene_frames(scene_clips, durations, qa_dir)
        for i, (frame, scene) in enumerate(zip(frames, script.scenes)):
            for issue in _llm_review_frame(
                frame, scene.id, scene.narration, expected_w, expected_h, llm
            ):
                result.add(issue)

    return result
