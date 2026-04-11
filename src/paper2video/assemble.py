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
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        "-r", str(fps),
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
               f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "-t", f"{duration_sec:.3f}",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def reframe_for_portrait(
    video_path: Path,
    audio_path: Path,
    duration_sec: float,
    out_path: Path,
    title_text: str = "",
    portrait_w: int = 1080,
    portrait_h: int = 1920,
    fps: int = 30,
) -> Path:
    """Reframe a landscape/square Manim clip into a portrait (9:16) video.

    Layout:
      - Top zone (~200px): title text on dark background
      - Middle zone (1080x1080): the Manim animation, scaled to fill
      - Bottom zone (~640px): reserved for subtitles (added later by burn_subtitles)
      - Audio muxed in

    The Manim clip is center-cropped/scaled to fill the middle 1080x1080 square.
    """
    ffmpeg = _ffmpeg()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    top_h = 200
    mid_h = 1080
    bot_h = portrait_h - top_h - mid_h  # 640 for 1920 total

    # Build the filter:
    # 1. Scale the manim video to fit 1080 wide, then crop to 1080x1080 from center
    # 2. Create a black canvas at portrait_w x portrait_h
    # 3. Overlay the cropped manim at y=top_h
    # 4. Draw title text in the top zone
    title_escaped = title_text.replace("'", "\u2019").replace(":", " -").replace("\\", "")
    title_filter = ""
    if title_text:
        title_filter = (
            f",drawtext=text='{title_escaped}'"
            f":fontsize=42:fontcolor=white"
            f":x=(w-text_w)/2:y=({top_h}-text_h)/2"
            f":font=Arial"
        )

    # Scale manim to fill portrait_w wide, then pad to mid_h tall (centered, black padding)
    vf = (
        f"[0:v]scale={portrait_w}:-1,pad={portrait_w}:{mid_h}:(ow-iw)/2:(oh-ih)/2:black[manim];"
        f"color=black:s={portrait_w}x{portrait_h}:d={duration_sec:.3f}:r={fps}[bg];"
        f"[bg][manim]overlay=0:{top_h}:shortest=1{title_filter}"
    )

    # Two-pass approach: first reframe video, then mux audio
    # This avoids complex filter_complex + multi-input mapping issues
    reframed_tmp = out_path.parent / f"{out_path.stem}_reframed.mp4"

    # Step 1: reframe video (no audio)
    cmd_video = [
        ffmpeg, "-y",
        "-i", str(video_path),
        "-filter_complex", vf,
        "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-t", f"{duration_sec:.3f}",
        str(reframed_tmp),
    ]
    res = subprocess.run(cmd_video, capture_output=True, text=True)
    if res.returncode != 0:
        # Fallback without drawtext (font might not be available)
        vf_simple = (
            f"[0:v]scale={portrait_w}:-1,pad={portrait_w}:{mid_h}:(ow-iw)/2:(oh-ih)/2:black[manim];"
            f"color=black:s={portrait_w}x{portrait_h}:d={duration_sec:.3f}:r={fps}[bg];"
            f"[bg][manim]overlay=0:{top_h}:shortest=1"
        )
        cmd_video_simple = [
            ffmpeg, "-y",
            "-i", str(video_path),
            "-filter_complex", vf_simple,
            "-an",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-t", f"{duration_sec:.3f}",
            str(reframed_tmp),
        ]
        subprocess.run(cmd_video_simple, check=True, capture_output=True)

    # Step 2: mux reframed video + audio
    cmd_mux = [
        ffmpeg, "-y",
        "-i", str(reframed_tmp),
        "-i", str(audio_path),
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        "-t", f"{duration_sec:.3f}",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd_mux, check=True, capture_output=True)

    # Cleanup
    reframed_tmp.unlink(missing_ok=True)
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
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
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
