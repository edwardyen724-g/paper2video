from __future__ import annotations
import argparse
import sys
from pathlib import Path
from dotenv import load_dotenv

from .pipeline import run_pipeline, PipelineConfig


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="paper2video",
        description="Turn a technical article or PDF into a narrated explainer video.",
    )
    p.add_argument("source", help="URL or local file path (HTML/PDF)")
    p.add_argument("--out", default="out", help="Output directory (default: ./out)")
    p.add_argument("--run-id", default="", help="Run subdirectory name (default: timestamp)")
    p.add_argument("--no-search", action="store_true", help="Skip web search in research stage")
    p.add_argument("--fake-tts", action="store_true", help="Use silent FakeTTS (fast, no deps)")
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--fps", type=int, default=30)
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
