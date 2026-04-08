# paper2video

**Turn any technical article or paper into a 2–5 minute narrated explainer video, in a 3Blue1Brown-ish style. Open-source end to end.**

```
URL or PDF  →  ingest  →  research  →  script  →  Manim render  →  Kokoro TTS  →  ffmpeg mux  →  video.mp4
```

Built in an afternoon by an LLM and one human who got tired of bouncing off research papers without ever actually understanding them. Inspired by an Andrej Karpathy gist about LLMs maintaining persistent wikis — which the author learned about *by generating and watching the explainer this tool produced*.

## Why this exists

There are way too many good ideas being published every day, and most of us never get to them because reading a paper is a 30-minute commitment with a 30% comprehension rate. paper2video tries to give you the *same understanding* in 3 minutes of audiovisual time. It's not a replacement for reading, but it's a much lower-friction first contact.

## What it does

1. **Ingests** any URL or PDF (HTML extraction via `trafilatura`, PDF via `pymupdf`)
2. **Researches** the topic — extracts key concepts, optionally pulls supporting context from DuckDuckGo
3. **Writes a script** as a sequence of animated scenes with narration
4. **Generates Manim code** for each scene by asking an LLM to write Python animation code
5. **Validates the code** with a static linter that catches the common cutoff/error bugs *before* rendering
6. **Renders the visuals** with [Manim Community Edition](https://www.manim.community/)
7. **Synthesizes narration** with [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) (~4.2 MOS, Apache 2.0, runs on CPU)
8. **Assembles** everything into a single MP4 with `ffmpeg`

Stage outputs are written to `out/<run_id>/` so you can resume, debug, or iterate on a single stage without rerunning the rest.

## Quickstart

```bash
git clone https://github.com/edwardyen724-g/paper2video.git
cd paper2video

python -m venv .venv
# Windows
.venv/Scripts/pip install -e ".[dev,tts,manim]"
# macOS/Linux
.venv/bin/pip install -e ".[dev,tts,manim]"

cp .env.example .env
# edit .env: paste your ANTHROPIC_API_KEY

paper2video https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
```

The output video will be at `out/<timestamp>/video.mp4`.

### System dependencies

| Tool | Why | How to install |
|---|---|---|
| **Python 3.11 or 3.12** | Kokoro currently doesn't have wheels for 3.13 | `uv python install 3.12` |
| **espeak-ng** | Kokoro's phonemizer | Win: `winget install eSpeak-NG.eSpeak-NG`  ·  macOS: `brew install espeak-ng`  ·  Linux: `apt install espeak-ng` |
| **ffmpeg** | Video assembly | Bundled via `imageio-ffmpeg` (auto-installed). No system install needed unless you prefer it. |

### Optional flags

```
paper2video <source> [flags]

  --run-id NAME      Output subdirectory name (default: timestamp)
  --no-search        Skip web search in research stage
  --fake-tts         Use silent FakeTTS (fast, no ML deps — useful for iterating on visuals)
  --width W          Video width  (default 1920)
  --height H         Video height (default 1080)
  --fps F            (default 30)
```

## Resumability

Each stage caches its output in `out/<run_id>/`:

- `ingest.json` — extracted source text
- `research.json` — concepts + key points
- `script.json` — the full scene-by-scene script
- `manim/scene_NNN.mp4` — rendered Manim clips
- `audio/scene_NNN.wav` — Kokoro narration
- `video.mp4` — final assembly

If you rerun with the same `--run-id`, the script and any already-rendered Manim scenes are reused. This means you can iterate on individual scenes by deleting just `manim/scene_004.mp4` and rerunning.

## Architecture

Five swappable interfaces, each with a fake implementation for testing:

| Interface | Default | Swap by |
|---|---|---|
| `LLMClient` | Anthropic Claude | Implement the protocol — Ollama, OpenAI, llama.cpp all fit |
| `TTSEngine` | Kokoro 82M | Implement the protocol — Coqui XTTS, F5-TTS, Chatterbox all fit |
| Renderer | Manim CE | Add a renderer module that takes a `Scene` |
| Ingest | trafilatura + pymupdf | Replace `extract_from_url` |
| Search | DuckDuckGo (`ddgs`) | Pass a custom `search` function to `research()` |

The pipeline orchestrator is ~120 lines (`src/paper2video/pipeline.py`). The whole thing is Python with no framework.

## Model selection

paper2video makes heavy use of LLM calls. The defaults are tuned for cost, quality, and reliability:

```
PAPER2VIDEO_MODEL=claude-haiku-4-5-20251001   # default — fast, cheap, good
```

Set in `.env`. Sonnet/Opus produce more visually ambitious Manim animations at higher cost. A typical run is one research call + one script call + N Manim codegen calls (1 per scene) + retry calls for any lint/render failures. Karpathy's gist run used about $0.05 of Haiku.

## Known limitations

- **Manim quality varies by model.** Haiku produces solid, clean animations. Sonnet produces noticeably more inventive ones at ~3x cost. Opus is overkill but tempting.
- **No subtitle burning yet.** Scene narration is in `script.json` but isn't drawn on-screen.
- **English only.** Kokoro supports more languages but the script prompt is English-only for now.
- **No diagram-from-equation pipeline.** Manim's `MathTex` requires LaTeX, which is excluded by the linter to keep installation easy. If you want equations, install LaTeX and remove that lint check.
- **Visuals are 720p30 by default.** Bump with `--height 1080 --fps 60` and pass `manim_quality="h"` in code if you want true 1080p60.

## Security

This tool runs LLM-generated Python code in a subprocess. See [SECURITY.md](SECURITY.md) for what we do to limit the blast radius and what we don't. Short version: a static linter blocks the obvious dangerous patterns (forbidden imports, `MathTex`, etc.) and code is run in a separate process — but it is not sandboxed, so don't run paper2video against sources you don't trust without a container.

## Tests

```bash
.venv/Scripts/python -m pytest -v
```

37 tests, all offline (use `FakeLLMClient` and `FakeTTS`). No API key needed.

## Contributing

Issues and PRs welcome. The codebase is small enough to read in one sitting:

```
src/paper2video/
  types.py             # pydantic data contracts
  llm.py               # LLMClient protocol + Anthropic + Fake
  ingest.py            # URL/HTML/PDF → text
  research.py          # concepts + search + synthesis
  script.py            # research → ScriptDoc with scenes
  renderers/
    base.py            # Renderer protocol
    slide.py           # matplotlib fallback
    manim_r.py         # LLM codegen + lint + render loop ← main visual engine
  tts.py               # TTSEngine protocol + Kokoro + Fake
  assemble.py          # ffmpeg muxing and concat
  pipeline.py          # the five-stage orchestrator
  cli.py               # paper2video command
```

## Credits

- Manim Community Edition — https://www.manim.community/
- Kokoro 82M — https://huggingface.co/hexgrad/Kokoro-82M
- Trafilatura, PyMuPDF, ddgs, ffmpeg, Anthropic Claude — without which this would be a shell of a script
- Andrej Karpathy's [LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — both the inspiration and the first thing this tool successfully explained

## License

Apache 2.0 — see [LICENSE](LICENSE).
