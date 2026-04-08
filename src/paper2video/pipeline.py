from __future__ import annotations
import json
import time
import traceback
from dataclasses import dataclass, asdict
from pathlib import Path

from .ingest import extract_from_url, extract_from_file, IngestedDoc
from .research import research, ResearchResult
from .script import write_script
from .renderers.slide import render_slide
from .renderers.manim_r import render_manim_scene, ManimRenderError
from .tts import TTSEngine, synthesize_scene_audio, SceneAudio
from .assemble import mux_scene_clip, concat_clips, build_scene_clip_from_image
from .llm import LLMClient
from .types import ScriptDoc, Scene


@dataclass
class PipelineConfig:
    out_dir: Path = Path("out")
    run_id: str = ""
    enable_search: bool = True
    width: int = 1920
    height: int = 1080
    fps: int = 30
    manim_quality: str = "m"  # l=480p15, m=720p30, h=1080p60
    manim_max_retries: int = 3
    use_manim: bool = True


@dataclass
class PipelineResult:
    run_dir: Path
    video_path: Path
    script: ScriptDoc


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str, ensure_ascii=False), encoding="utf-8")


def _is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def _log(run_dir: Path, msg: str) -> None:
    print(f"[pipeline] {msg}")
    (run_dir / "pipeline.log").open("a", encoding="utf-8").write(msg + "\n")


def _render_scene_visual(
    scene: Scene,
    duration_sec: float,
    run_dir: Path,
    llm: LLMClient,
    cfg: PipelineConfig,
) -> tuple[Path, str]:
    """Render one scene's visual track. Returns (mp4_or_png_path, kind) where kind is 'video' or 'image'."""
    if cfg.use_manim:
        try:
            manim_dir = run_dir / "manim"
            mp4 = render_manim_scene(
                scene=scene,
                duration_sec=duration_sec,
                out_dir=manim_dir,
                llm=llm,
                quality=cfg.manim_quality,
                max_retries=cfg.manim_max_retries,
            )
            _log(run_dir, f"  scene {scene.id}: manim OK -> {mp4.name}")
            return mp4, "video"
        except ManimRenderError as e:
            _log(run_dir, f"  scene {scene.id}: manim FAILED after retries, falling back to slide. err: {e.message}")
            (run_dir / "manim" / f"scene_{scene.id:03d}.err.txt").write_text(
                e.stderr + "\n\n---LAST CODE---\n" + e.last_code, encoding="utf-8"
            )
        except Exception as e:
            _log(run_dir, f"  scene {scene.id}: manim crashed: {e}\n{traceback.format_exc()}")

    # Fallback: matplotlib slide
    img_dir = run_dir / "images"
    png = render_slide(scene, img_dir, size=(cfg.width, cfg.height))
    return png, "image"


def run_pipeline(
    source: str,
    config: PipelineConfig,
    llm: LLMClient,
    tts: TTSEngine,
) -> PipelineResult:
    run_id = config.run_id or time.strftime("%Y%m%d-%H%M%S")
    run_dir = Path(config.out_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    _log(run_dir, f"=== run_id={run_id} ===")

    # 1-3. Ingest / Research / Script — cached as script.json for resumability
    script_cache = run_dir / "script.json"
    if script_cache.exists():
        _log(run_dir, "stage: script (CACHED — reusing script.json)")
        script_doc = ScriptDoc.model_validate_json(script_cache.read_text(encoding="utf-8"))
        _log(run_dir, f"  title={script_doc.title!r} scenes={len(script_doc.scenes)}")
    else:
        _log(run_dir, "stage: ingest")
        if _is_url(source):
            doc: IngestedDoc = extract_from_url(source)
        else:
            doc = extract_from_file(Path(source))
        _write_json(run_dir / "ingest.json", asdict(doc))
        _log(run_dir, f"  title={doc.title!r} chars={len(doc.text)}")

        _log(run_dir, "stage: research")
        research_result: ResearchResult = research(doc, llm=llm, enable_search=config.enable_search)
        _write_json(run_dir / "research.json", {
            "concepts": research_result.concepts,
            "notes": [n.model_dump() for n in research_result.notes],
            "key_points": research_result.key_points,
        })
        _log(run_dir, f"  concepts={research_result.concepts}")

        _log(run_dir, "stage: script")
        script_doc = write_script(research_result, llm=llm)
        _write_json(script_cache, script_doc.model_dump())
        _log(run_dir, f"  title={script_doc.title!r} scenes={len(script_doc.scenes)}")

    # 4. TTS FIRST — so we know per-scene durations before rendering visuals.
    _log(run_dir, "stage: tts")
    audio_dir = run_dir / "audio"
    scene_audios: list[SceneAudio] = [
        synthesize_scene_audio(s, tts, audio_dir) for s in script_doc.scenes
    ]
    for s, a in zip(script_doc.scenes, scene_audios):
        _log(run_dir, f"  scene {s.id}: audio {a.duration_sec:.2f}s")

    # 5. Render visuals per scene (Manim primary, slide fallback)
    _log(run_dir, "stage: render visuals")
    visual_tracks: list[tuple[Path, str]] = []
    for s, a in zip(script_doc.scenes, scene_audios):
        path_kind = _render_scene_visual(s, a.duration_sec, run_dir, llm, config)
        visual_tracks.append(path_kind)

    # 6. Mux audio + video per scene (with pad/trim to audio duration), then concat
    _log(run_dir, "stage: mux + concat")
    work_dir = run_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    scene_clips: list[Path] = []
    for s, a, (visual_path, kind) in zip(script_doc.scenes, scene_audios, visual_tracks):
        clip_out = work_dir / f"scene_{s.id:03d}.mp4"
        if kind == "video":
            mux_scene_clip(
                video_path=visual_path,
                audio_path=a.audio_path,
                duration_sec=a.duration_sec,
                out_path=clip_out,
                width=config.width,
                height=config.height,
                fps=config.fps,
            )
        else:
            # Image: loop image for duration + attach audio
            build_scene_clip_from_image(
                image_path=visual_path,
                audio_path=a.audio_path,
                duration_sec=a.duration_sec,
                out_path=clip_out,
                width=config.width,
                height=config.height,
                fps=config.fps,
            )
        scene_clips.append(clip_out)

    video_path = run_dir / "video.mp4"
    concat_clips(scene_clips, video_path, work_dir)
    _log(run_dir, f"DONE: {video_path}")

    return PipelineResult(run_dir=run_dir, video_path=video_path, script=script_doc)
