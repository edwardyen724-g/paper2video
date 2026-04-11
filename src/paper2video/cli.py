from __future__ import annotations
import argparse
import hashlib
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

from .pipeline import run_pipeline, PipelineConfig
from .publish import CommandPublisher, FakePublisher, PublisherRegistry
from .review import FakeTelegramReviewClient, TelegramReviewClient
from .social import (
    SocialWorkflowDependencies,
    approve_and_publish,
    generate_social_draft,
    process_next_queued_item,
    process_telegram_updates,
    revise_social_draft,
)
from .store import JobStore
from .types import ContentItem, SocialGenerationConfig
from .watchers import queue_discovered_content

log = logging.getLogger("paper2video")


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
    p.add_argument("--run-loop", action="store_true", help="Run one full automation pass: discover -> generate -> poll Telegram -> publish")
    p.add_argument("--setup-oauth", metavar="PLATFORM", help="Run interactive OAuth setup for a platform (youtube, tiktok, instagram)")
    p.add_argument("--install-scheduler", action="store_true", help="Register a Windows Scheduled Task to run the loop every 30 minutes")
    p.add_argument("--uninstall-scheduler", action="store_true", help="Remove the Paper2Video Windows Scheduled Task")
    return p


def _build_publisher_registry() -> PublisherRegistry:
    """Build a PublisherRegistry with available API publishers + command fallbacks."""
    # Start with command-based fallback for platforms that have env var commands
    cmd_map = {
        k: v for k, v in {
            "tiktok": os.environ.get("PAPER2VIDEO_TIKTOK_PUBLISH_CMD", ""),
            "instagram": os.environ.get("PAPER2VIDEO_INSTAGRAM_PUBLISH_CMD", ""),
            "xiaohongshu": os.environ.get("PAPER2VIDEO_XIAOHONGSHU_PUBLISH_CMD", ""),
            "youtube": os.environ.get("PAPER2VIDEO_YOUTUBE_PUBLISH_CMD", ""),
        }.items() if v
    }
    default = CommandPublisher(cmd_map) if cmd_map else FakePublisher()
    registry = PublisherRegistry(default=default)

    tokens_dir = Path(".tokens")

    # YouTube API publisher
    try:
        from .publishers.youtube import YouTubePublisher
        if (tokens_dir / "youtube.json").exists():
            registry.register("youtube", YouTubePublisher(tokens_dir))
            log.info("YouTube API publisher loaded.")
    except ImportError:
        pass

    # TikTok API publisher
    try:
        from .publishers.tiktok import TikTokPublisher
        if (tokens_dir / "tiktok.json").exists():
            registry.register("tiktok", TikTokPublisher(tokens_dir))
            log.info("TikTok API publisher loaded.")
    except ImportError:
        pass

    # Instagram API publisher
    try:
        from .publishers.instagram import InstagramPublisher
        if (tokens_dir / "instagram.json").exists():
            registry.register("instagram", InstagramPublisher(tokens_dir))
            log.info("Instagram API publisher loaded.")
    except ImportError:
        pass

    return registry


def _run_oauth_setup(platform: str) -> int:
    """Run interactive OAuth setup for a platform."""
    from .publishers import run_oauth_setup

    platform = platform.lower()
    configs = {
        "youtube": {
            "client_id_env": "YOUTUBE_CLIENT_ID",
            "client_secret_env": "YOUTUBE_CLIENT_SECRET",
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "scopes": [
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube.force-ssl",
            ],
        },
        "tiktok": {
            "client_id_env": "TIKTOK_CLIENT_KEY",
            "client_secret_env": "TIKTOK_CLIENT_SECRET",
            "auth_url": "https://www.tiktok.com/v2/auth/authorize/",
            "token_url": "https://open.tiktokapis.com/v2/oauth/token/",
            "scopes": ["video.upload", "video.publish"],
        },
        "instagram": {
            "client_id_env": "INSTAGRAM_CLIENT_ID",
            "client_secret_env": "INSTAGRAM_CLIENT_SECRET",
            "auth_url": "https://www.facebook.com/v21.0/dialog/oauth",
            "token_url": "https://graph.facebook.com/v21.0/oauth/access_token",
            "scopes": [
                "instagram_basic",
                "instagram_content_publish",
                "pages_read_engagement",
            ],
        },
    }

    if platform not in configs:
        print(f"Unknown platform: {platform}. Choose from: {', '.join(configs)}", file=sys.stderr)
        return 1

    cfg = configs[platform]
    client_id = os.environ.get(cfg["client_id_env"], "")
    client_secret = os.environ.get(cfg["client_secret_env"], "")
    if not client_id or not client_secret:
        print(f"Set {cfg['client_id_env']} and {cfg['client_secret_env']} in .env first.", file=sys.stderr)
        return 1

    run_oauth_setup(
        platform=platform,
        client_id=client_id,
        client_secret=client_secret,
        auth_url=cfg["auth_url"],
        token_url=cfg["token_url"],
        scopes=cfg["scopes"],
    )
    return 0


def _run_social_loop(cfg: SocialGenerationConfig, deps: SocialWorkflowDependencies) -> int:
    """Run one full automation pass: discover -> generate -> poll Telegram -> publish."""
    # Step 1: Discover new content from feeds
    queued = queue_discovered_content(deps.store)
    if queued:
        log.info("Discovered %d new items.", len(queued))

    # Step 2: Generate ONE draft if nothing is in progress or awaiting review
    active = deps.store.list_items_by_state("draft_generating", "awaiting_review")
    if not active:
        draft = process_next_queued_item(cfg=cfg, deps=deps)
        if draft:
            log.info("Generated draft: %s", draft.item.source_id)
    else:
        log.info("Skipping generation: %d items in progress/review.", len(active))

    # Step 3: Poll Telegram for review callbacks
    processed = process_telegram_updates(cfg=cfg, deps=deps)
    if processed:
        log.info("Processed %d Telegram updates.", processed)

    # Step 4: Publish any approved items
    approved = deps.store.list_items_by_state("approved")
    for item in approved:
        results = approve_and_publish(item.source_id, deps=deps)
        for r in results:
            log.info("Publish %s/%s: %s", item.source_id, r.platform, r.publish_status)

    return 0


def _install_scheduler() -> int:
    """Register a Windows Scheduled Task to run the loop every 30 minutes."""
    import subprocess

    python_exe = sys.executable
    working_dir = os.getcwd()
    cmd = f'"{python_exe}" -m paper2video --mode social_review --run-loop'

    ps_script = f"""
$action = New-ScheduledTaskAction `
    -Execute '{python_exe}' `
    -Argument '-m paper2video --mode social_review --run-loop' `
    -WorkingDirectory '{working_dir}'

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration ([TimeSpan]::MaxValue)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName 'Paper2Video-SocialLoop' `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description 'Runs paper2video social workflow loop every 30 minutes' `
    -Force
"""
    result = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Failed to install scheduler:\n{result.stderr}", file=sys.stderr)
        return 1
    print("Scheduled task 'Paper2Video-SocialLoop' installed (every 30 min).")
    print(f"  Command: {cmd}")
    print(f"  Working dir: {working_dir}")
    return 0


def _uninstall_scheduler() -> int:
    """Remove the Paper2Video Windows Scheduled Task."""
    import subprocess

    result = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-Command",
         "Unregister-ScheduledTask -TaskName 'Paper2Video-SocialLoop' -Confirm:$false"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Failed to uninstall scheduler:\n{result.stderr}", file=sys.stderr)
        return 1
    print("Scheduled task 'Paper2Video-SocialLoop' removed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv(override=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    args = build_parser().parse_args(argv)

    # Handle standalone commands that don't need LLM/TTS
    if args.setup_oauth:
        return _run_oauth_setup(args.setup_oauth)
    if args.install_scheduler:
        return _install_scheduler()
    if args.uninstall_scheduler:
        return _uninstall_scheduler()

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
        publisher = _build_publisher_registry()
        deps = SocialWorkflowDependencies(
            llm=llm,
            tts=tts,
            store=store,
            review_client=review_client,
            publisher=publisher,
        )
        cfg = SocialGenerationConfig(enable_search=not args.no_search)

        if args.run_loop:
            return _run_social_loop(cfg, deps)
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
