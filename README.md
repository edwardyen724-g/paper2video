# paper2video

Turn a technical article or paper into a 2–5 minute narrated explainer video.
All open-source. Pluggable LLM, swappable renderers, local TTS.

## Quickstart

```
pip install -e ".[dev,tts]"
cp .env.example .env  # add your ANTHROPIC_API_KEY
paper2video https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
```

## Architecture

```
ingest → research → script → render → tts → assemble
```

Each stage writes to `out/<run_id>/<stage>.json` so you can resume/debug.

## Flags

- `--no-search` — skip web search in research stage
- `--fake-tts` — use silent FakeTTS (fast, no ML deps)
- `--run-id NAME` — custom output subdirectory
