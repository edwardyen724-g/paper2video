from __future__ import annotations
import argparse
import hashlib
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

from .pipeline import run_pipeline, PipelineConfig
from .review import FakeTelegramReviewClient, TelegramReviewClient
from .publish import CommandPublisher, FakePublisher
from .social import (
    SocialWorkflowDependencies,
    approve_and_publish,
    generate_social_draft,
    process_telegram_updates,
    revise_social_draft,
)
from .store import JobStore
from .types import ContentItem, SocialGenerationConfig
from .watchers import queue_discovered_content


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="paper2video",
        description="Turn a technical article or PDF into a narrated explainer video.",
    )
    p.add_argument("source", nargs="?", help="URL or local file path (HTML/PDF)")
    p.add_argument("--out", default="out", help="Output directory (default: ./out)")
    p.add_argument("--run-id", default="", help="Run subdirectory name (default: timestamp)")
    p.add_argument("--no-search", action="store_true", help="Skip web search in research stage")
    p.add_argument("--fake-tts", action="store_true", help="Use silent FakeTTS (fast, no deps)")
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--mode", choices=["longform", "social_review"], default="longform")
    p.add_argument("--db", default="out/social/workflow.db", help="SQLite job store path for social workflow")
    p.add_argument("--approve-source-id", default="", help="Approve and publish an existing social draft by source ID")
    p.add_argument("--revise-source-id", default="", help="Revise an existing social draft by source ID")
    p.add_argument("--revision-message", default="", help="Free-text revision instruction")
    p.add_argument("--watch-once", action="store_true", help="Poll configured social sources once and enqueue drafts")
    p.add_argument("--poll-telegram-once", action="store_true", help="Poll Telegram once and process review callbacks/messages")
    return p


def main(argv: list[str] | None = None) -> int:
    load_dotenv(override=True)
    args = build_parser().parse_args(argv)

    from .llm import AnthropicClient
    llm = AnthropicClient()

    if args.fake_tts:
        from .tts import FakeTTS
        tts = FakeTTS()
    else:
        try:
            from .tts import KokoroTTS
            tts = KokoroTTS()
        except ImportError as e:
            print(f"[warn] Kokoro not available ({e}); falling back to FakeTTS. "
                  f"Install with: pip install -e '.[tts]'", file=sys.stderr)
            from .tts import FakeTTS
            tts = FakeTTS()

    if args.mode == "social_review":
        store = JobStore(Path(args.db))
        if "TELEGRAM_BOT_TOKEN" in os.environ and "TELEGRAM_CHAT_ID" in os.environ:
            review_client = TelegramReviewClient(
                bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
                chat_id=os.environ["TELEGRAM_CHAT_ID"],
            )
        else:
            review_client = FakeTelegramReviewClient()
        publish_commands = {
            "tiktok": os.environ.get("PAPER2VIDEO_TIKTOK_PUBLISH_CMD", ""),
            "instagram": os.environ.get("PAPER2VIDEO_INSTAGRAM_PUBLISH_CMD", ""),
            "xiaohongshu": os.environ.get("PAPER2VIDEO_XIAOHONGSHU_PUBLISH_CMD", ""),
        }
        publisher = (
            CommandPublisher({k: v for k, v in publish_commands.items() if v})
            if any(publish_commands.values())
            else FakePublisher()
        )
        deps = SocialWorkflowDependencies(
            llm=llm,
            tts=tts,
            store=store,
            review_client=review_client,
            publisher=publisher,
        )
        cfg = SocialGenerationConfig(enable_search=not args.no_search)
        if args.approve_source_id:
            results = approve_and_publish(args.approve_source_id, deps=deps)
            for result in results:
                print(f"{result.platform}: {result.publish_status}")
            return 0
        if args.revise_source_id:
            if not args.revision_message:
                raise SystemExit("--revision-message is required with --revise-source-id")
            draft = revise_social_draft(args.revise_source_id, args.revision_message, cfg=cfg, deps=deps)
            print(f"review video: {draft.review_video_path}")
            print(f"run dir: {draft.run_dir}")
            return 0
        if args.watch_once:
            queued = queue_discovered_content(store)
            print(f"queued: {len(queued)}")
            if queued:
                draft = generate_social_draft(item=queued[0], cfg=cfg, deps=deps)
                print(f"review video: {draft.review_video_path}")
                print(f"run dir: {draft.run_dir}")
            return 0
        if args.poll_telegram_once:
            processed = process_telegram_updates(cfg=cfg, deps=deps)
            print(f"processed updates: {processed}")
            return 0
        if not args.source:
            raise SystemExit("source is required for --mode social_review")
        manual_id = hashlib.sha1(args.source.encode("utf-8")).hexdigest()[:12]
        item = ContentItem(
            source_id=f"manual:{manual_id}",
            title=args.source,
            source_type="openai_blog" if args.source.startswith("http") else "arxiv",
            source_priority=100,
            canonical_url=args.source,
            state="queued",
        )
        draft = generate_social_draft(item=item, cfg=cfg, deps=deps)
        print(f"review video: {draft.review_video_path}")
        print(f"run dir: {draft.run_dir}")
        return 0

    cfg = PipelineConfig(
        out_dir=Path(args.out),
        run_id=args.run_id,
        enable_search=not args.no_search,
        width=args.width,
        height=args.height,
        fps=args.fps,
    )
    result = run_pipeline(args.source, cfg, llm=llm, tts=tts)
    print(f"video: {result.video_path}")
    print(f"run dir: {result.run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
