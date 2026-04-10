"""paper2video — Hugging Face Space demo.

Paste a URL, get a narrated 3Blue1Brown-style explainer video back.
"""
import os
import shutil
import tempfile
import time
from pathlib import Path

import gradio as gr

# Ensure HF Space secrets are loaded
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = os.environ.get("PAPER2VIDEO_MODEL", "claude-haiku-4-5-20251001")


def generate_video(
    url: str,
    enable_search: bool,
    progress=gr.Progress(track_tqdm=False),
):
    if not url.strip():
        raise gr.Error("Please enter a URL.")
    if not ANTHROPIC_API_KEY:
        raise gr.Error(
            "ANTHROPIC_API_KEY not set. Add it as a Space secret in Settings."
        )

    # Late imports so the Space loads fast even if deps are heavy
    from paper2video.pipeline import run_pipeline, PipelineConfig
    from paper2video.llm import AnthropicClient
    from paper2video.tts import FakeTTS

    # Try Kokoro, fall back to FakeTTS (silent) if deps missing
    try:
        from paper2video.tts import KokoroTTS
        tts = KokoroTTS()
        tts_name = "Kokoro 82M"
    except Exception:
        tts = FakeTTS()
        tts_name = "FakeTTS (silent — espeak-ng may be missing)"

    progress(0.05, desc="Initializing...")
    llm = AnthropicClient(model=MODEL, api_key=ANTHROPIC_API_KEY)

    run_id = f"space_{int(time.time())}"
    out_dir = Path(tempfile.mkdtemp(prefix="p2v_"))
    cfg = PipelineConfig(
        out_dir=out_dir,
        run_id=run_id,
        enable_search=enable_search,
        manim_quality="m",  # 720p30 — good balance of quality and speed
    )

    progress(0.10, desc="Ingesting article...")
    from paper2video.ingest import extract_from_url, IngestedDoc
    doc = extract_from_url(url.strip())
    if not doc.text.strip():
        raise gr.Error("Could not extract text from that URL. Try a different article.")

    progress(0.20, desc=f"Researching concepts{' (with web search)' if enable_search else ''}...")
    from paper2video.research import research
    research_result = research(doc, llm=llm, enable_search=enable_search)

    progress(0.35, desc="Writing script...")
    from paper2video.script import write_script
    script_doc = write_script(research_result, llm=llm)
    n_scenes = len(script_doc.scenes)

    progress(0.40, desc=f"Generating {tts_name} voiceover for {n_scenes} scenes...")
    from paper2video.tts import synthesize_scene_audio
    audio_dir = out_dir / run_id / "audio"
    scene_audios = [synthesize_scene_audio(s, tts, audio_dir) for s in script_doc.scenes]

    progress(0.55, desc=f"Rendering {n_scenes} Manim scenes (this takes a minute)...")
    from paper2video.renderers.manim_r import render_manim_scene, ManimRenderError
    from paper2video.renderers.slide import render_slide

    manim_dir = out_dir / run_id / "manim"
    img_dir = out_dir / run_id / "images"
    visual_tracks = []
    for i, (scene, audio) in enumerate(zip(script_doc.scenes, scene_audios)):
        pct = 0.55 + (i / n_scenes) * 0.30
        progress(pct, desc=f"Rendering scene {scene.id}/{n_scenes}...")
        try:
            mp4 = render_manim_scene(
                scene=scene,
                duration_sec=audio.duration_sec,
                out_dir=manim_dir,
                llm=llm,
                quality="m",
                max_retries=2,
            )
            visual_tracks.append((mp4, "video"))
        except (ManimRenderError, Exception):
            # Fallback to slide
            png = render_slide(scene, img_dir, size=(cfg.width, cfg.height))
            visual_tracks.append((png, "image"))

    progress(0.90, desc="Assembling final video...")
    from paper2video.assemble import mux_scene_clip, build_scene_clip_from_image, concat_clips
    work_dir = out_dir / run_id / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    scene_clips = []
    for scene, audio, (visual_path, kind) in zip(script_doc.scenes, scene_audios, visual_tracks):
        clip = work_dir / f"scene_{scene.id:03d}.mp4"
        if kind == "video":
            mux_scene_clip(visual_path, audio.audio_path, audio.duration_sec, clip,
                           cfg.width, cfg.height, cfg.fps)
        else:
            build_scene_clip_from_image(visual_path, audio.audio_path, audio.duration_sec, clip,
                                        cfg.width, cfg.height, cfg.fps)
        scene_clips.append(clip)

    video_path = out_dir / run_id / "video.mp4"
    concat_clips(scene_clips, video_path, work_dir)

    progress(1.0, desc="Done!")
    return str(video_path)


# ---- Gradio UI ----

DESCRIPTION = """
## paper2video

Turn any technical article into a **narrated 3Blue1Brown-style explainer video**.

- Paste a URL (blog post, paper, gist)
- Wait 3–5 minutes
- Get a 2–5 minute video with Manim animations and AI narration

**Stack:** Claude (script + Manim codegen) → Manim CE (animation) → Kokoro 82M (voice) → ffmpeg (assembly)

[GitHub repo](https://github.com/edwardyen724-g/paper2video) · Apache 2.0
"""

EXAMPLES = [
    ["https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f", True],
    ["https://www.anthropic.com/engineering/harness-design-long-running-apps", True],
]

demo = gr.Interface(
    fn=generate_video,
    inputs=[
        gr.Textbox(
            label="Article URL",
            placeholder="https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f",
            lines=1,
        ),
        gr.Checkbox(label="Enable web search (richer research, slightly slower)", value=True),
    ],
    outputs=gr.Video(label="Generated Explainer Video"),
    title="paper2video",
    description=DESCRIPTION,
    examples=EXAMPLES,
    cache_examples=False,
    concurrency_limit=1,  # One generation at a time (heavy compute)
    flagging_mode="never",
)

if __name__ == "__main__":
    demo.launch()
