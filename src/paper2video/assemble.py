from __future__ import annotations
import shutil
import subprocess
from pathlib import Path


class FFmpegNotFound(RuntimeError):
    pass


def _ffmpeg() -> str:
    """Resolve ffmpeg: prefer system install, fall back to imageio-ffmpeg static binary."""
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg  # type: ignore
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        raise FFmpegNotFound(
            f"ffmpeg not found on PATH and imageio-ffmpeg fallback failed: {e}. "
            f"Install system ffmpeg or `pip install imageio-ffmpeg`."
        )


def _ffprobe_duration(path: Path) -> float | None:
    """Probe duration with ffprobe if available. Returns None if ffprobe isn't present."""
    probe = shutil.which("ffprobe")
    if not probe:
        return None
    res = subprocess.run(
        [probe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        return None
    try:
        return float(res.stdout.strip())
    except ValueError:
        return None


def build_concat_list(clip_paths: list[Path]) -> str:
    """Produce contents of an ffmpeg concat demuxer file."""
    lines = []
    for p in clip_paths:
        abs_posix = Path(p).resolve().as_posix()
        lines.append(f"file '{abs_posix}'")
    return "\n".join(lines) + "\n"


def build_scene_clip_from_image(
    image_path: Path,
    audio_path: Path,
    duration_sec: float,
    out_path: Path,
    width: int,
    height: int,
    fps: int,
) -> Path:
    """Loop a still image for `duration_sec` and mux in audio. Fallback clip builder."""
    ffmpeg = _ffmpeg()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-loop", "1", "-i", str(image_path),
        "-i", str(audio_path),
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-r", str(fps),
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
               f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "-t", f"{duration_sec:.3f}",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def mux_scene_clip(
    video_path: Path,
    audio_path: Path,
    duration_sec: float,
    out_path: Path,
    width: int,
    height: int,
    fps: int,
) -> Path:
    """Combine a silent video with audio, pad/trim video to match `duration_sec`.

    If the video is shorter than the audio, freeze the last frame (tpad clone).
    If longer, trim it.
    """
    ffmpeg = _ffmpeg()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={fps},"
        # Pad with a clone of the last frame if video is shorter than duration
        f"tpad=stop_mode=clone:stop_duration={duration_sec:.3f}"
    )

    cmd = [
        ffmpeg, "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-filter_complex", f"[0:v]{vf}[v]",
        "-map", "[v]",
        "-map", "1:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{duration_sec:.3f}",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def concat_clips(clip_paths: list[Path], out_path: Path, work_dir: Path) -> Path:
    """Concat already-muxed clips via the ffmpeg concat demuxer.

    Clips must share the same codec, fps, sample rate, and resolution.
    """
    ffmpeg = _ffmpeg()
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    concat_file = work_dir / "concat.txt"
    concat_file.write_text(build_concat_list(clip_paths), encoding="utf-8")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Re-encode on concat to avoid codec-parameter mismatch between clips
    # (Manim output and image-loop output may differ in subtle ways)
    cmd = [
        ffmpeg, "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


# Backwards-compat shim for the old test_assemble.py and anything importing assemble_video
def assemble_video(
    images: list[Path],
    audio_paths: list[Path],
    durations: list[float],
    out_path: Path,
    work_dir: Path,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
) -> Path:
    assert len(images) == len(audio_paths) == len(durations), "mismatched scene lists"
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    clips = []
    for i, (img, aud, dur) in enumerate(zip(images, audio_paths, durations), start=1):
        clip = work_dir / f"clip_{i:03d}.mp4"
        build_scene_clip_from_image(img, aud, dur, clip, width, height, fps)
        clips.append(clip)
    return concat_clips(clips, out_path, work_dir)
