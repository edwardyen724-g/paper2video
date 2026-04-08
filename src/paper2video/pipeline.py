from __future__ import annotations
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from .ingest import extract_from_url, extract_from_file, IngestedDoc
from .research import research, ResearchResult
from .script import write_script
from .renderers.slide import render_slide
from .tts import TTSEngine, synthesize_scene_audio
from .assemble import assemble_video
from .llm import LLMClient
from .types import ScriptDoc


@dataclass
class PipelineConfig:
    out_dir: Path = Path("out")
    run_id: str = ""
    enable_search: bool = True
    width: int = 1920
    height: int = 1080
    fps: int = 30


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


def run_pipeline(
    source: str,
    config: PipelineConfig,
    llm: LLMClient,
    tts: TTSEngine,
) -> PipelineResult:
    run_id = config.run_id or time.strftime("%Y%m%d-%H%M%S")
    run_dir = Path(config.out_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # 1. Ingest
    if _is_url(source):
        doc: IngestedDoc = extract_from_url(source)
    else:
        doc = extract_from_file(Path(source))
    _write_json(run_dir / "ingest.json", asdict(doc))

    # 2. Research
    research_result: ResearchResult = research(doc, llm=llm, enable_search=config.enable_search)
    _write_json(run_dir / "research.json", {
        "concepts": research_result.concepts,
        "notes": [n.model_dump() for n in research_result.notes],
        "key_points": research_result.key_points,
    })

    # 3. Script
    script_doc = write_script(research_result, llm=llm)
    _write_json(run_dir / "script.json", script_doc.model_dump())

    # 4. Render slides
    img_dir = run_dir / "images"
    images = [render_slide(s, img_dir, size=(config.width, config.height)) for s in script_doc.scenes]

    # 5. TTS
    audio_dir = run_dir / "audio"
    scene_audios = [synthesize_scene_audio(s, tts, audio_dir) for s in script_doc.scenes]

    # 6. Assemble
    video_path = assemble_video(
        images=images,
        audio_paths=[a.audio_path for a in scene_audios],
        durations=[a.duration_sec for a in scene_audios],
        out_path=run_dir / "video.mp4",
        work_dir=run_dir / "work",
        width=config.width,
        height=config.height,
        fps=config.fps,
    )

    return PipelineResult(run_dir=run_dir, video_path=video_path, script=script_doc)
