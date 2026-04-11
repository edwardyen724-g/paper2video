from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from .assemble import build_scene_clip_from_image, concat_clips, mux_scene_clip, reframe_for_portrait
from .captions import burn_subtitles, write_srt
from .ingest import IngestedDoc, extract_from_url
from .llm import LLMClient
from .pipeline import _render_scene_visual
from .publish import Publisher, PublisherRegistry, build_platform_packages
from .qa import run_qa, QAResult
from .research import research
from .review import ReviewClient, parse_telegram_message
from .script import revise_social_script, write_social_script
from .store import JobStore
from .tts import TTSEngine, SceneAudio, _wav_duration, synthesize_scene_audio
from .types import ContentItem, PublishResultRecord, ReviewActionRecord, ScriptDoc, SocialDraft, SocialGenerationConfig
from .validate import validate_vertical_assets


@dataclass
class SocialWorkflowDependencies:
    llm: LLMClient
    tts: TTSEngine
    store: JobStore
    review_client: ReviewClient
    publisher: Publisher


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _social_run_dir(cfg: SocialGenerationConfig, item: ContentItem, revision_count: int) -> Path:
    base = Path(cfg.out_dir) / item.source_id.replace(":", "_")
    suffix = "draft" if revision_count == 0 else f"revision_{revision_count:02d}"
    return base / suffix


def _load_script(path: Path) -> ScriptDoc:
    return ScriptDoc.model_validate_json(path.read_text(encoding="utf-8"))


def _render_social_video(
    item: ContentItem,
    doc: IngestedDoc,
    script_doc: ScriptDoc,
    cfg: SocialGenerationConfig,
    deps: SocialWorkflowDependencies,
    run_dir: Path,
    rerender_scene_ids: set[int] | None = None,
    prior_run_dir: Path | None = None,
) -> SocialDraft:
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / "ingest.json", {"text": doc.text, "title": doc.title, "source_url": doc.source_url})
    _write_json(run_dir / "script.json", script_doc.model_dump())

    audio_dir = run_dir / "audio"
    images_dir = run_dir / "images"
    work_dir = run_dir / "work"
    audio_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    rerender_scene_ids = rerender_scene_ids or {scene.id for scene in script_doc.scenes}

    scene_audios = []
    visual_tracks: list[tuple[Path, str]] = []

    for scene in script_doc.scenes:
        audio_path = audio_dir / f"scene_{scene.id:03d}.wav"
        if prior_run_dir and scene.id not in rerender_scene_ids:
            prior_audio = prior_run_dir / "audio" / f"scene_{scene.id:03d}.wav"
            if prior_audio.exists():
                audio_path.write_bytes(prior_audio.read_bytes())
        if not audio_path.exists():
            scene_audio = synthesize_scene_audio(scene, deps.tts, audio_dir)
        else:
            scene_audio = SceneAudio(scene_id=scene.id, audio_path=audio_path, duration_sec=_wav_duration(audio_path))
        scene_audios.append(scene_audio)

        if prior_run_dir and scene.id not in rerender_scene_ids:
            prior_manim = prior_run_dir / "manim" / f"scene_{scene.id:03d}.mp4"
            prior_image = prior_run_dir / "images" / f"scene_{scene.id:03d}.png"
            if prior_manim.exists():
                target = run_dir / "manim" / prior_manim.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(prior_manim.read_bytes())
                visual_tracks.append((target, "video"))
                continue
            if prior_image.exists():
                target = images_dir / prior_image.name
                target.write_bytes(prior_image.read_bytes())
                visual_tracks.append((target, "image"))
                continue

        visual_tracks.append(
            _render_scene_visual(
                scene=scene,
                duration_sec=scene_audios[-1].duration_sec,
                run_dir=run_dir,
                llm=deps.llm,
                cfg=type("Cfg", (), {
                    "use_manim": cfg.use_manim,
                    "manim_quality": "m",
                    "manim_max_retries": 2,
                    "width": cfg.width,
                    "height": cfg.height,
                    "fps": cfg.fps,
                })(),
            )
        )

    is_portrait = cfg.height > cfg.width
    from .tts import FakeTTS
    from .llm import FakeLLMClient
    is_test = isinstance(deps.tts, FakeTTS) or isinstance(deps.llm, FakeLLMClient)

    def _build_scene_clip(scene, audio, visual_path, kind):
        clip_out = work_dir / f"scene_{scene.id:03d}.mp4"
        if is_portrait and kind == "video":
            scene_title = (scene.visual_spec or {}).get("title", "")
            reframe_for_portrait(
                video_path=visual_path, audio_path=audio.audio_path,
                duration_sec=audio.duration_sec, out_path=clip_out,
                title_text=scene_title, portrait_w=cfg.width,
                portrait_h=cfg.height, fps=cfg.fps,
            )
        elif kind == "video":
            mux_scene_clip(
                video_path=visual_path, audio_path=audio.audio_path,
                duration_sec=audio.duration_sec, out_path=clip_out,
                width=cfg.width, height=cfg.height, fps=cfg.fps,
            )
        else:
            build_scene_clip_from_image(
                image_path=visual_path, audio_path=audio.audio_path,
                duration_sec=audio.duration_sec, out_path=clip_out,
                width=cfg.width, height=cfg.height, fps=cfg.fps,
            )
        return clip_out

    # Build clips + QA retry loop (max 2 retries for scenes with visual errors)
    max_qa_retries = 0 if is_test else 2
    clip_paths: list[Path] = []
    for scene, audio, (visual_path, kind) in zip(script_doc.scenes, scene_audios, visual_tracks):
        clip_paths.append(_build_scene_clip(scene, audio, visual_path, kind))

    qa_dir = run_dir / "qa"
    for qa_attempt in range(max_qa_retries + 1):
        master_video = run_dir / "master.mp4"
        concat_clips(clip_paths, master_video, work_dir)

        qa_result = run_qa(
            video_path=master_video, audio_dir=run_dir / "audio",
            script=script_doc, expected_w=cfg.width, expected_h=cfg.height,
            scene_clips=clip_paths if not is_test else None,
            durations=[a.duration_sec for a in scene_audios] if not is_test else None,
            llm=deps.llm if not is_test else None,
            qa_dir=qa_dir / f"attempt_{qa_attempt}",
            skip_audio_check=is_test, skip_pacing_check=is_test,
        )

        bad_scene_ids = qa_result.error_scene_ids
        if not bad_scene_ids or qa_attempt >= max_qa_retries:
            break

        # Re-render bad scenes: delete cached Manim clips so they regenerate
        for sid in bad_scene_ids:
            manim_clip = run_dir / "manim" / f"scene_{sid:03d}.mp4"
            manim_work = run_dir / "manim" / f"scene_{sid:03d}_work"
            manim_clip.unlink(missing_ok=True)
            if manim_work.exists():
                import shutil
                shutil.rmtree(manim_work, ignore_errors=True)

        # Re-render and rebuild clips for bad scenes
        for idx, scene in enumerate(script_doc.scenes):
            if scene.id not in bad_scene_ids:
                continue
            audio = scene_audios[idx]
            vt = _render_scene_visual(
                scene=scene, duration_sec=audio.duration_sec,
                run_dir=run_dir, llm=deps.llm,
                cfg=type("Cfg", (), {
                    "use_manim": cfg.use_manim, "manim_quality": "m",
                    "manim_max_retries": 2, "width": cfg.width,
                    "height": cfg.height, "fps": cfg.fps,
                })(),
            )
            visual_tracks[idx] = vt
            clip_paths[idx] = _build_scene_clip(scene, audio, vt[0], vt[1])

    # Final assembly
    durations = [audio.duration_sec for audio in scene_audios]
    captions_path = write_srt(run_dir / "captions.srt", script_doc.scenes, durations)
    review_video = burn_subtitles(master_video, captions_path, run_dir / "review.mp4", portrait=is_portrait) if cfg.captions_enabled else master_video

    validation_errors = validate_vertical_assets(
        script=script_doc,
        visual_paths=[path for path, _ in visual_tracks],
        audio_paths=[audio.audio_path for audio in scene_audios],
        captions_path=captions_path if cfg.captions_enabled else None,
        expected_size=(cfg.width, cfg.height),
    )

    # Log final QA results
    qa_log = run_dir / "qa_report.json"
    _write_json(qa_log, {
        "passed": qa_result.passed,
        "issues": [
            {"severity": i.severity, "scene_id": i.scene_id, "category": i.category, "message": i.message}
            for i in qa_result.issues
        ],
    })
    for issue in qa_result.issues:
        if issue.severity == "error":
            validation_errors.append(f"[QA {issue.category}] scene {issue.scene_id}: {issue.message}")

    draft_item = item.model_copy(
        update={
            "latest_run_dir": str(run_dir),
            "summary": script_doc.summary,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )
    return SocialDraft(
        item=draft_item,
        script=script_doc,
        run_dir=str(run_dir),
        master_video_path=str(master_video),
        review_video_path=str(review_video),
        captions_path=str(captions_path),
        validation_errors=validation_errors,
    )


def generate_social_draft(
    item: ContentItem,
    cfg: SocialGenerationConfig,
    deps: SocialWorkflowDependencies,
) -> SocialDraft:
    item = deps.store.upsert_item(item.model_copy(update={"state": "draft_generating"}))
    doc = extract_from_url(item.canonical_url)
    research_result = research(doc, llm=deps.llm, enable_search=cfg.enable_search)
    run_dir = _social_run_dir(cfg, item, item.revision_count)
    _write_json(
        run_dir / "research.json",
        {
            "concepts": research_result.concepts,
            "notes": [note.model_dump() for note in research_result.notes],
            "key_points": research_result.key_points,
        },
    )
    script_doc = write_social_script(research_result, llm=deps.llm)
    draft = _render_social_video(item, doc, script_doc, cfg, deps, run_dir)
    if draft.validation_errors:
        failed = item.model_copy(update={"state": "failed", "latest_run_dir": str(run_dir), "summary": draft.script.summary})
        deps.store.upsert_item(failed)
        return draft
    awaiting = item.model_copy(update={"state": "awaiting_review", "latest_run_dir": str(run_dir), "summary": draft.script.summary})
    awaiting = deps.store.upsert_item(awaiting)
    draft = draft.model_copy(update={"item": awaiting})
    deps.review_client.send_draft(draft)
    return draft


def revise_social_draft(
    source_id: str,
    instruction: str,
    cfg: SocialGenerationConfig,
    deps: SocialWorkflowDependencies,
) -> SocialDraft:
    item = deps.store.increment_revision_count(source_id)
    item = deps.store.upsert_item(item.model_copy(update={"state": "revision_requested"}))
    deps.store.record_review_action(
        ReviewActionRecord(source_id=source_id, action_type="revise", reviewer_message=instruction)
    )
    prior_run_dir = Path(item.latest_run_dir)
    script_doc = _load_script(prior_run_dir / "script.json")
    revised_script, changed_scene_ids = revise_social_script(script_doc, instruction, llm=deps.llm)
    doc = extract_from_url(item.canonical_url)
    run_dir = _social_run_dir(cfg, item, item.revision_count)
    draft = _render_social_video(
        item=item,
        doc=doc,
        script_doc=revised_script,
        cfg=cfg,
        deps=deps,
        run_dir=run_dir,
        rerender_scene_ids=set(changed_scene_ids or [scene.id for scene in revised_script.scenes]),
        prior_run_dir=prior_run_dir,
    )
    state = "failed" if draft.validation_errors else "awaiting_review"
    updated_item = item.model_copy(update={"state": state, "latest_run_dir": str(run_dir), "summary": draft.script.summary})
    updated_item = deps.store.upsert_item(updated_item)
    draft = draft.model_copy(update={"item": updated_item})
    if not draft.validation_errors:
        deps.review_client.send_draft(draft)
    return draft


def approve_and_publish(
    source_id: str,
    deps: SocialWorkflowDependencies,
) -> list[PublishResultRecord]:
    item = deps.store.get_item(source_id)
    deps.store.record_review_action(ReviewActionRecord(source_id=source_id, action_type="approve"))
    item = deps.store.upsert_item(item.model_copy(update={"state": "approved"}))
    run_dir = Path(item.latest_run_dir)
    master_video_path = Path(item.approved_master_asset_path or (run_dir / "master.mp4"))
    item = deps.store.upsert_item(
        item.model_copy(update={"state": "publishing", "approved_master_asset_path": str(master_video_path)})
    )
    packages = build_platform_packages(item, master_video_path, run_dir / "packages")
    results: list[PublishResultRecord] = []
    for package in packages:
        existing = {result.platform: result for result in deps.store.list_publish_results(source_id)}
        if package.platform in existing and existing[package.platform].publish_status == "published":
            results.append(existing[package.platform])
            continue
        if isinstance(deps.publisher, PublisherRegistry):
            pub = deps.publisher.get(package.platform)
            if pub is None:
                continue
        else:
            pub = deps.publisher
        result = pub.publish(item, package)
        if result.packaging_status == "pending":
            result.packaging_status = "packaged"
        deps.store.upsert_publish_result(source_id, result)
        results.append(result)
    final_state = "published" if all(result.publish_status == "published" for result in results) else "failed"
    deps.store.upsert_item(item.model_copy(update={"state": final_state}))
    return results


def skip_item(source_id: str, deps: SocialWorkflowDependencies, reviewer_message: str = "") -> ContentItem:
    deps.store.record_review_action(
        ReviewActionRecord(source_id=source_id, action_type="skip", reviewer_message=reviewer_message)
    )
    item = deps.store.get_item(source_id)
    return deps.store.upsert_item(item.model_copy(update={"state": "skipped"}))


def process_next_queued_item(
    cfg: SocialGenerationConfig,
    deps: SocialWorkflowDependencies,
) -> SocialDraft | None:
    queued = deps.store.list_items_by_state("queued")
    if not queued:
        return None
    return generate_social_draft(queued[0], cfg=cfg, deps=deps)


def process_telegram_updates(
    cfg: SocialGenerationConfig,
    deps: SocialWorkflowDependencies,
    timeout_sec: int = 0,
) -> int:
    review_client = deps.review_client
    if not all(hasattr(review_client, attr) for attr in ("get_updates", "answer_callback_query", "send_text")):
        return 0

    offset = int(deps.store.get_meta("telegram_update_offset", "0") or "0")
    updates = review_client.get_updates(offset=offset if offset > 0 else None, timeout=timeout_sec)
    if not updates:
        return 0

    processed = 0
    max_update_id = offset
    for update in updates:
        update_id = int(update.get("update_id", 0))
        max_update_id = max(max_update_id, update_id)

        if "callback_query" in update:
            callback = update["callback_query"]
            callback_id = str(callback.get("id", ""))
            action_data = str(callback.get("data", ""))
            action, _, source_id = action_data.partition(":")
            chat_id = str(((callback.get("message") or {}).get("chat") or {}).get("id", ""))

            if action == "approve":
                review_client.answer_callback_query(callback_id, "Publishing approved.")
                results = approve_and_publish(source_id, deps=deps)
                review_client.send_text(
                    f"Approved and publish attempted for {source_id}: "
                    + ", ".join(f"{r.platform}={r.publish_status}" for r in results),
                    chat_id=chat_id or None,
                )
            elif action == "skip":
                review_client.answer_callback_query(callback_id, "Skipped.")
                skip_item(source_id, deps=deps)
                review_client.send_text(f"Skipped {source_id}.", chat_id=chat_id or None)
            elif action == "revise":
                review_client.answer_callback_query(callback_id, "Reply with your revision instruction.")
                deps.store.set_pending_revision(chat_id, source_id)
                review_client.send_text(
                    f"Reply with the change you want for {source_id}. Example: make the intro punchier.",
                    chat_id=chat_id or None,
                )
            else:
                review_client.answer_callback_query(callback_id, "Unknown action.")
            processed += 1
            continue

        if "message" in update:
            chat_id, text, _message_id = parse_telegram_message(update)
            if not text or text.startswith("/"):
                processed += 1
                continue
            pending_source_id = deps.store.get_pending_revision(chat_id)
            if pending_source_id:
                deps.store.clear_pending_revision(chat_id)
                review_client.send_text(
                    f"Revision received for {pending_source_id}. Generating updated draft now.",
                    chat_id=chat_id or None,
                )
                revise_social_draft(pending_source_id, text, cfg=cfg, deps=deps)
            processed += 1

    deps.store.set_meta("telegram_update_offset", str(max_update_id + 1))
    return processed
