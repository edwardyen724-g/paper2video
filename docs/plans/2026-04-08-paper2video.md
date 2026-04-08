# paper2video — Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking. Implement task-by-task, committing after each task.

**Goal:** Build an open-source pipeline that turns a URL or PDF of a technical article into a 2–5 minute narrated explainer video with visual scenes, using only open-source tools.

**Architecture:** A Python package (`paper2video`) with a linear pipeline — `ingest → research → script → render scenes → tts → assemble` — orchestrated by a small CLI. Each stage is a pure module with an explicit data contract (typed dicts/dataclasses), so stages can be swapped or rerun independently. Heavy ML dependencies (Manim, Kokoro TTS) are lazy-imported so the core pipeline is testable without them, and the baseline renderer uses matplotlib/Pillow so you can smoke-test end-to-end on a fresh machine.

**Tech Stack:**
- **Language:** Python 3.11+
- **Ingest:** `trafilatura` (HTML article extraction), `pymupdf` (PDF)
- **LLM:** `anthropic` SDK (Claude via API key), wrapped behind a `LLMClient` protocol so Ollama/OpenAI can drop in
- **Research:** minimal in-house loop using DuckDuckGo HTML search (`ddgs`) + trafilatura — no paid search API
- **Baseline visuals:** `matplotlib` + `Pillow` (slide-style scenes with text, equations, diagrams)
- **Advanced visuals (optional):** `manim` (Community Edition) for 3Blue1Brown-style math animation
- **TTS:** `kokoro` (82M, Apache 2.0, ~4.2 MOS, runs on CPU)
- **Assembly:** `ffmpeg` via `subprocess` (no moviepy — too heavy, flaky on Windows)
- **Testing:** `pytest`, `pytest-mock`
- **Packaging:** `pyproject.toml` with `uv` or `pip`

**Key design decisions:**
- LLM calls go through a single `LLMClient` interface with a `FakeLLMClient` for tests — no network in unit tests.
- Scenes are described by a `Scene` dataclass (`narration`, `visual_type`, `visual_spec`), produced by the script stage and consumed by the renderer. This decouples "what to say/show" from "how to draw it".
- Each stage writes its output to `out/<run_id>/<stage>.json` so you can resume, debug, and swap stages.
- Baseline slide renderer is the default; Manim is opt-in via `visual_type: "manim"` in a scene spec. This means the pipeline works end-to-end without LaTeX installed.

**Out of scope for this plan:**
- Voice cloning (Kokoro default voice only)
- Real-time preview UI
- Multi-language output (English only)
- Fine-grained Manim auto-healing loops (we generate Manim scripts but fall back to slides on render failure)

---

## File Structure

```
learning-ideas/
├── pyproject.toml
├── README.md
├── .gitignore
├── .env.example
├── docs/plans/2026-04-08-paper2video.md        (this file)
├── src/paper2video/
│   ├── __init__.py
│   ├── types.py           # Scene, ScriptDoc, ResearchNote dataclasses
│   ├── llm.py             # LLMClient protocol, AnthropicClient, FakeLLMClient
│   ├── ingest.py          # URL/PDF → clean text
│   ├── research.py        # iterative search + synthesis
│   ├── script.py          # research notes → Scene list
│   ├── renderers/
│   │   ├── __init__.py
│   │   ├── base.py        # Renderer protocol
│   │   ├── slide.py       # matplotlib slide renderer (default)
│   │   └── manim_r.py     # Manim renderer (optional, lazy import)
│   ├── tts.py             # Kokoro wrapper + FakeTTS for tests
│   ├── assemble.py        # ffmpeg concat of scene clips + audio
│   ├── pipeline.py        # orchestrates the stages, writes stage outputs
│   └── cli.py             # `paper2video <url>` entry point
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   ├── karpathy_gist.html
│   │   └── sample_script.json
│   ├── test_ingest.py
│   ├── test_llm.py
│   ├── test_research.py
│   ├── test_script.py
│   ├── test_slide_renderer.py
│   ├── test_tts.py
│   ├── test_assemble.py
│   └── test_pipeline.py
└── out/                    # run outputs (gitignored)
```

Each file has one responsibility. `types.py` is the shared contract all stages import from — changes here ripple, so it lands early in the plan.

---

## Prerequisites (one-time setup, not a task)

Before Task 1, the engineer should have:
- Python 3.11+
- `ffmpeg` on PATH. Windows: `winget install Gyan.FFmpeg`. macOS: `brew install ffmpeg`. Linux: `apt install ffmpeg`.
- `ANTHROPIC_API_KEY` in environment (or `.env`) — only needed for live runs, not unit tests.
- (Optional, for Kokoro TTS) `espeak-ng` on PATH. Windows: `winget install eSpeak-NG.eSpeak-NG`.
- (Optional, for Manim) LaTeX distribution + Cairo. Windows: MiKTeX. See Manim docs.

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `README.md`
- Create: `src/paper2video/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "paper2video"
version = "0.1.0"
description = "Open-source pipeline: article/paper -> narrated explainer video"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.40.0",
    "trafilatura>=1.12.0",
    "pymupdf>=1.24.0",
    "ddgs>=0.9.0",
    "matplotlib>=3.9.0",
    "Pillow>=10.4.0",
    "python-dotenv>=1.0.1",
    "pydantic>=2.9.0",
]

[project.optional-dependencies]
tts = ["kokoro>=0.7.0", "soundfile>=0.12.1"]
manim = ["manim>=0.18.0"]
dev = ["pytest>=8.3.0", "pytest-mock>=3.14.0", "ruff>=0.6.0"]

[project.scripts]
paper2video = "paper2video.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: Create `.gitignore`**

```
__pycache__/
*.pyc
.pytest_cache/
.venv/
venv/
.env
out/
*.egg-info/
dist/
build/
```

- [ ] **Step 3: Create `.env.example`**

```
ANTHROPIC_API_KEY=sk-ant-...
PAPER2VIDEO_MODEL=claude-sonnet-4-6
PAPER2VIDEO_OUT_DIR=./out
```

- [ ] **Step 4: Create `README.md`**

```markdown
# paper2video

Turn a technical article or paper into a 2–5 minute narrated explainer video.
All open-source. Pluggable LLM, swappable renderers, local TTS.

## Quickstart

    pip install -e ".[dev,tts]"
    cp .env.example .env  # add your ANTHROPIC_API_KEY
    paper2video https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

## Architecture

    ingest → research → script → render → tts → assemble

Each stage writes to `out/<run_id>/<stage>.json` so you can resume/debug.
```

- [ ] **Step 5: Create empty package init files**

`src/paper2video/__init__.py`:
```python
"""paper2video — open-source article-to-video pipeline."""
__version__ = "0.1.0"
```

`tests/__init__.py`: empty file.

- [ ] **Step 6: Create `tests/conftest.py`**

```python
import sys
from pathlib import Path

# Ensure src/ is importable before package is installed
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
```

- [ ] **Step 7: Initialize git and install dev deps**

```bash
cd C:/projects/learning-ideas
git init
git add .
git commit -m "chore: project scaffold"
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
```

Expected: `pip install` succeeds. `pytest` runs and reports "no tests collected" (no tests yet — that's fine).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "chore: install dev dependencies"
```

---

## Task 2: Shared Types

**Files:**
- Create: `src/paper2video/types.py`
- Test: `tests/test_types.py`

These are the contracts every stage reads/writes. Define them once.

- [ ] **Step 1: Write the failing test**

`tests/test_types.py`:
```python
from paper2video.types import Scene, ScriptDoc, ResearchNote, Source


def test_scene_roundtrip_json():
    s = Scene(
        id=1,
        narration="Hello world.",
        visual_type="slide",
        visual_spec={"title": "Intro", "bullets": ["one", "two"]},
        duration_hint_sec=5.0,
    )
    data = s.model_dump()
    assert Scene.model_validate(data) == s


def test_script_doc_holds_scenes():
    doc = ScriptDoc(
        title="Test",
        summary="A test.",
        scenes=[
            Scene(id=1, narration="Hi.", visual_type="slide",
                  visual_spec={"title": "Hi"}, duration_hint_sec=2.0)
        ],
    )
    assert len(doc.scenes) == 1
    assert doc.scenes[0].id == 1


def test_research_note_has_source():
    note = ResearchNote(
        claim="LLMs can maintain wikis.",
        sources=[Source(url="https://example.com", title="Example")],
    )
    assert note.sources[0].url == "https://example.com"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/pytest tests/test_types.py -v
```
Expected: ImportError, `paper2video.types` does not exist.

- [ ] **Step 3: Write the implementation**

`src/paper2video/types.py`:
```python
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field

VisualType = Literal["slide", "manim", "image"]


class Source(BaseModel):
    url: str
    title: str = ""


class ResearchNote(BaseModel):
    claim: str
    sources: list[Source] = Field(default_factory=list)


class Scene(BaseModel):
    id: int
    narration: str
    visual_type: VisualType = "slide"
    visual_spec: dict = Field(default_factory=dict)
    duration_hint_sec: float = 5.0


class ScriptDoc(BaseModel):
    title: str
    summary: str
    scenes: list[Scene]
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/pytest tests/test_types.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(types): Scene, ScriptDoc, ResearchNote contracts"
```

---

## Task 3: LLM Client Abstraction

**Files:**
- Create: `src/paper2video/llm.py`
- Test: `tests/test_llm.py`

A thin protocol so every other module takes an `LLMClient` parameter. Tests inject `FakeLLMClient`; real runs inject `AnthropicClient`.

- [ ] **Step 1: Write the failing test**

`tests/test_llm.py`:
```python
from paper2video.llm import FakeLLMClient, LLMClient


def test_fake_llm_returns_queued_responses():
    llm: LLMClient = FakeLLMClient(responses=["first", "second"])
    assert llm.complete("prompt a") == "first"
    assert llm.complete("prompt b") == "second"


def test_fake_llm_records_prompts():
    llm = FakeLLMClient(responses=["x"])
    llm.complete("hello")
    assert llm.calls == [("hello", None)]


def test_fake_llm_json_mode():
    llm = FakeLLMClient(responses=['{"k": 1}'])
    result = llm.complete_json("give me json")
    assert result == {"k": 1}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/pytest tests/test_llm.py -v
```
Expected: ImportError on `paper2video.llm`.

- [ ] **Step 3: Write the implementation**

`src/paper2video/llm.py`:
```python
from __future__ import annotations
import json
import os
from typing import Protocol


class LLMClient(Protocol):
    def complete(self, prompt: str, system: str | None = None) -> str: ...
    def complete_json(self, prompt: str, system: str | None = None) -> dict: ...


class FakeLLMClient:
    """Test double. Returns queued responses in order."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[tuple[str, str | None]] = []

    def complete(self, prompt: str, system: str | None = None) -> str:
        self.calls.append((prompt, system))
        if not self._responses:
            raise RuntimeError("FakeLLMClient ran out of responses")
        return self._responses.pop(0)

    def complete_json(self, prompt: str, system: str | None = None) -> dict:
        raw = self.complete(prompt, system)
        return json.loads(raw)


class AnthropicClient:
    """Production LLM client backed by Anthropic API."""

    def __init__(self, model: str | None = None, api_key: str | None = None):
        import anthropic  # lazy
        self._client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self.model = model or os.environ.get("PAPER2VIDEO_MODEL", "claude-sonnet-4-6")

    def complete(self, prompt: str, system: str | None = None) -> str:
        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        msg = self._client.messages.create(**kwargs)
        return msg.content[0].text

    def complete_json(self, prompt: str, system: str | None = None) -> dict:
        sys_prompt = (system or "") + "\n\nRespond with valid JSON only. No prose, no code fences."
        raw = self.complete(prompt, sys_prompt.strip())
        raw = raw.strip()
        if raw.startswith("```"):
            # strip code fences if the model ignored the instruction
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw.rsplit("```", 1)[0]
        return json.loads(raw)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/pytest tests/test_llm.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(llm): LLMClient protocol with Fake and Anthropic impls"
```

---

## Task 4: Ingest (URL / PDF → clean text)

**Files:**
- Create: `src/paper2video/ingest.py`
- Create: `tests/fixtures/sample_article.html`
- Test: `tests/test_ingest.py`

- [ ] **Step 1: Create the fixture file**

`tests/fixtures/sample_article.html`:
```html
<!DOCTYPE html>
<html><head><title>Sample Article</title></head>
<body>
<nav>nav stuff to strip</nav>
<article>
<h1>The Main Idea</h1>
<p>This is the first paragraph of real content that trafilatura should extract.</p>
<p>And here is the second paragraph with more substance to the actual article body.</p>
</article>
<footer>footer junk</footer>
</body></html>
```

- [ ] **Step 2: Write the failing test**

`tests/test_ingest.py`:
```python
from pathlib import Path
from paper2video.ingest import extract_from_html, extract_from_file, IngestedDoc

FIXTURE = Path(__file__).parent / "fixtures" / "sample_article.html"


def test_extract_from_html_returns_clean_text():
    html = FIXTURE.read_text(encoding="utf-8")
    doc = extract_from_html(html, source_url="https://example.com/a")
    assert isinstance(doc, IngestedDoc)
    assert "first paragraph" in doc.text
    assert "nav stuff" not in doc.text
    assert "footer junk" not in doc.text
    assert doc.source_url == "https://example.com/a"


def test_extract_from_file_dispatches_on_suffix(tmp_path):
    html_copy = tmp_path / "a.html"
    html_copy.write_bytes(FIXTURE.read_bytes())
    doc = extract_from_file(html_copy)
    assert "first paragraph" in doc.text
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
.venv/Scripts/pytest tests/test_ingest.py -v
```
Expected: ImportError.

- [ ] **Step 4: Write the implementation**

`src/paper2video/ingest.py`:
```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import urllib.request


@dataclass
class IngestedDoc:
    text: str
    title: str
    source_url: str


def extract_from_html(html: str, source_url: str = "") -> IngestedDoc:
    import trafilatura
    text = trafilatura.extract(html, include_comments=False, include_tables=True) or ""
    meta = trafilatura.extract_metadata(html)
    title = meta.title if meta and meta.title else ""
    return IngestedDoc(text=text.strip(), title=title, source_url=source_url)


def extract_from_pdf(path: Path) -> IngestedDoc:
    import pymupdf  # type: ignore
    doc = pymupdf.open(path)
    try:
        parts = [page.get_text() for page in doc]
    finally:
        doc.close()
    text = "\n\n".join(parts).strip()
    return IngestedDoc(text=text, title=path.stem, source_url=str(path))


def extract_from_file(path: Path) -> IngestedDoc:
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        return extract_from_pdf(path)
    html = path.read_text(encoding="utf-8", errors="replace")
    return extract_from_html(html, source_url=str(path))


def extract_from_url(url: str, timeout: float = 30.0) -> IngestedDoc:
    req = urllib.request.Request(url, headers={"User-Agent": "paper2video/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    # Try HTML first; if it looks like a PDF, save and parse
    if raw[:4] == b"%PDF":
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(raw)
            tmp = Path(f.name)
        try:
            doc = extract_from_pdf(tmp)
        finally:
            tmp.unlink(missing_ok=True)
        return IngestedDoc(text=doc.text, title=doc.title, source_url=url)
    html = raw.decode("utf-8", errors="replace")
    return extract_from_html(html, source_url=url)
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
.venv/Scripts/pytest tests/test_ingest.py -v
```
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(ingest): URL/HTML/PDF text extraction"
```

---

## Task 5: Research Module

**Files:**
- Create: `src/paper2video/research.py`
- Test: `tests/test_research.py`

The research stage takes an ingested doc and has the LLM (a) list the key concepts that need explanation, (b) optionally search the web for each, and (c) synthesize notes. For this MVP, we skip live web search in unit tests and make it injectable. The real function uses `ddgs` under the hood.

- [ ] **Step 1: Write the failing test**

`tests/test_research.py`:
```python
import json
from paper2video.llm import FakeLLMClient
from paper2video.research import research, ResearchResult
from paper2video.ingest import IngestedDoc


def fake_search(query: str, max_results: int = 3):
    return [{"title": f"{query} - result", "url": "https://example.com", "snippet": "snippet"}]


def test_research_identifies_concepts_and_synthesizes():
    doc = IngestedDoc(text="LLMs can build wikis.", title="Wiki", source_url="https://x")
    # First LLM call: list concepts (JSON array)
    # Second LLM call: synthesize notes (JSON)
    llm = FakeLLMClient(responses=[
        '["LLM", "wiki", "RAG"]',
        '{"notes": [{"claim": "LLMs maintain wikis", "sources": [{"url": "https://example.com", "title": "r"}]}], "key_points": ["point 1", "point 2"]}',
    ])
    result = research(doc, llm=llm, search=fake_search, max_concepts=3)
    assert isinstance(result, ResearchResult)
    assert len(result.concepts) == 3
    assert "LLM" in result.concepts
    assert len(result.notes) >= 1
    assert result.key_points == ["point 1", "point 2"]


def test_research_skips_search_when_disabled():
    doc = IngestedDoc(text="t", title="", source_url="")
    calls = []

    def tracking_search(q, max_results=3):
        calls.append(q)
        return []

    llm = FakeLLMClient(responses=[
        '["a"]',
        '{"notes": [], "key_points": ["only from article"]}',
    ])
    result = research(doc, llm=llm, search=tracking_search, enable_search=False)
    assert calls == []
    assert result.key_points == ["only from article"]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/pytest tests/test_research.py -v
```
Expected: ImportError.

- [ ] **Step 3: Write the implementation**

`src/paper2video/research.py`:
```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable
from .ingest import IngestedDoc
from .llm import LLMClient
from .types import ResearchNote, Source


SearchFn = Callable[[str, int], list[dict]]


@dataclass
class ResearchResult:
    concepts: list[str]
    notes: list[ResearchNote]
    key_points: list[str]
    source_text: str = ""


def _default_search(query: str, max_results: int = 3) -> list[dict]:
    """Live DuckDuckGo search — no API key required."""
    from ddgs import DDGS
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))


CONCEPTS_PROMPT = """You are helping produce a 2-5 minute explainer video for a technical article.
Read the article below and list the 3-6 most important concepts a smart novice would need to understand.
Return ONLY a JSON array of short concept names.

ARTICLE:
{text}
"""

SYNTHESIS_PROMPT = """You are producing research notes for an explainer video about this article.

ARTICLE:
{text}

ADDITIONAL CONTEXT FROM WEB SEARCH:
{search_context}

Produce JSON with this exact shape:
{{
  "notes": [
    {{"claim": "...", "sources": [{{"url": "...", "title": "..."}}]}}
  ],
  "key_points": ["3-6 short bullet points capturing the main ideas"]
}}

Rules:
- Notes should be factual claims grounded in the article or search results.
- key_points should be the story beats for the video, in order.
- Output JSON only.
"""


def research(
    doc: IngestedDoc,
    llm: LLMClient,
    search: SearchFn | None = None,
    max_concepts: int = 5,
    enable_search: bool = True,
) -> ResearchResult:
    search = search or _default_search

    concepts_raw = llm.complete_json(CONCEPTS_PROMPT.format(text=doc.text[:12000]))
    if isinstance(concepts_raw, list):
        concepts = [str(c) for c in concepts_raw][:max_concepts]
    else:
        concepts = [str(c) for c in concepts_raw.get("concepts", [])][:max_concepts]

    search_context_parts: list[str] = []
    if enable_search:
        for concept in concepts:
            try:
                results = search(concept, 3)
            except Exception as e:  # degrade gracefully
                results = []
                search_context_parts.append(f"[search failed for {concept}: {e}]")
                continue
            for r in results:
                title = r.get("title", "")
                url = r.get("href") or r.get("url", "")
                snippet = r.get("body") or r.get("snippet", "")
                search_context_parts.append(f"- {title} ({url}): {snippet}")

    search_context = "\n".join(search_context_parts) if search_context_parts else "(none)"

    synthesis = llm.complete_json(
        SYNTHESIS_PROMPT.format(text=doc.text[:12000], search_context=search_context)
    )
    notes = [
        ResearchNote(
            claim=n["claim"],
            sources=[Source(**s) for s in n.get("sources", [])],
        )
        for n in synthesis.get("notes", [])
    ]
    key_points = [str(p) for p in synthesis.get("key_points", [])]

    return ResearchResult(
        concepts=concepts,
        notes=notes,
        key_points=key_points,
        source_text=doc.text,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/pytest tests/test_research.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(research): LLM-driven concept extraction + optional web search"
```

---

## Task 6: Script Module

**Files:**
- Create: `src/paper2video/script.py`
- Test: `tests/test_script.py`

Takes `ResearchResult` and produces a `ScriptDoc` — the list of scenes ready to render.

- [ ] **Step 1: Write the failing test**

`tests/test_script.py`:
```python
from paper2video.llm import FakeLLMClient
from paper2video.research import ResearchResult
from paper2video.script import write_script
from paper2video.types import ScriptDoc


def test_write_script_returns_valid_script_doc():
    research_result = ResearchResult(
        concepts=["LLM", "wiki"],
        notes=[],
        key_points=["intro", "body", "outro"],
        source_text="article text",
    )
    llm_response = """{
      "title": "LLMs as Wiki Builders",
      "summary": "How LLMs maintain persistent wikis.",
      "scenes": [
        {"id": 1, "narration": "Welcome.", "visual_type": "slide",
         "visual_spec": {"title": "LLM Wikis", "bullets": ["a"]}, "duration_hint_sec": 5.0},
        {"id": 2, "narration": "Here's why.", "visual_type": "slide",
         "visual_spec": {"title": "Why", "bullets": ["b"]}, "duration_hint_sec": 6.0}
      ]
    }"""
    llm = FakeLLMClient(responses=[llm_response])
    doc = write_script(research_result, llm=llm)
    assert isinstance(doc, ScriptDoc)
    assert doc.title == "LLMs as Wiki Builders"
    assert len(doc.scenes) == 2
    assert doc.scenes[0].narration == "Welcome."
    assert doc.scenes[1].visual_spec["title"] == "Why"


def test_write_script_enforces_scene_ids():
    research_result = ResearchResult(concepts=[], notes=[], key_points=["x"], source_text="t")
    # Response with missing ids — script.py should assign them
    llm = FakeLLMClient(responses=["""{
      "title": "T", "summary": "S",
      "scenes": [
        {"narration": "a", "visual_type": "slide", "visual_spec": {"title": "A"}, "duration_hint_sec": 3.0},
        {"narration": "b", "visual_type": "slide", "visual_spec": {"title": "B"}, "duration_hint_sec": 3.0}
      ]
    }"""])
    doc = write_script(research_result, llm=llm)
    assert [s.id for s in doc.scenes] == [1, 2]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/pytest tests/test_script.py -v
```
Expected: ImportError.

- [ ] **Step 3: Write the implementation**

`src/paper2video/script.py`:
```python
from __future__ import annotations
from .llm import LLMClient
from .research import ResearchResult
from .types import Scene, ScriptDoc


SCRIPT_PROMPT = """You are writing the script for a 2-5 minute explainer video in the style of
3Blue1Brown: clear, visual, progressive. The audience is a smart novice.

INPUT ARTICLE:
{source_text}

KEY POINTS (story beats, in order):
{key_points}

RESEARCH NOTES:
{notes}

Produce a JSON object with this exact shape:
{{
  "title": "short video title",
  "summary": "one-sentence summary",
  "scenes": [
    {{
      "narration": "what the narrator says, 1-3 sentences, plain text no markdown",
      "visual_type": "slide",
      "visual_spec": {{
        "title": "scene title (<=60 chars)",
        "bullets": ["short bullet 1", "short bullet 2"],
        "caption": "optional 1-line caption"
      }},
      "duration_hint_sec": 5.0
    }}
  ]
}}

Constraints:
- 5 to 12 scenes total.
- Each narration 1-3 sentences, spoken English, no jargon without a plain-English gloss.
- Total narration should read in 2-5 minutes (~150 words per minute).
- visual_type must be "slide" for every scene (other types not yet supported).
- Every visual_spec MUST include "title" and "bullets" (bullets may be empty).
- Output JSON only, no prose, no code fences.
"""


def write_script(research_result: ResearchResult, llm: LLMClient) -> ScriptDoc:
    notes_str = "\n".join(f"- {n.claim}" for n in research_result.notes) or "(none)"
    key_points_str = "\n".join(f"- {p}" for p in research_result.key_points) or "(none)"

    raw = llm.complete_json(
        SCRIPT_PROMPT.format(
            source_text=research_result.source_text[:10000],
            key_points=key_points_str,
            notes=notes_str,
        )
    )

    scenes: list[Scene] = []
    for i, s in enumerate(raw.get("scenes", []), start=1):
        scenes.append(
            Scene(
                id=s.get("id") or i,
                narration=s["narration"],
                visual_type=s.get("visual_type", "slide"),
                visual_spec=s.get("visual_spec", {}),
                duration_hint_sec=float(s.get("duration_hint_sec", 5.0)),
            )
        )

    return ScriptDoc(
        title=raw.get("title", "Untitled"),
        summary=raw.get("summary", ""),
        scenes=scenes,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/pytest tests/test_script.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(script): ResearchResult -> ScriptDoc via LLM"
```

---

## Task 7: Slide Renderer (Baseline Visual)

**Files:**
- Create: `src/paper2video/renderers/__init__.py`
- Create: `src/paper2video/renderers/base.py`
- Create: `src/paper2video/renderers/slide.py`
- Test: `tests/test_slide_renderer.py`

The slide renderer draws a scene as a PNG (one per scene). Video clips per scene are built at assembly time by ffmpeg looping the PNG for the scene's audio duration, so the renderer output is images, not videos.

- [ ] **Step 1: Create the package init**

`src/paper2video/renderers/__init__.py`:
```python
from .slide import render_slide  # noqa: F401
```

- [ ] **Step 2: Create the base protocol**

`src/paper2video/renderers/base.py`:
```python
from __future__ import annotations
from pathlib import Path
from typing import Protocol
from ..types import Scene


class Renderer(Protocol):
    def render(self, scene: Scene, out_dir: Path) -> Path:
        """Render a scene to a file and return the path."""
        ...
```

- [ ] **Step 3: Write the failing test**

`tests/test_slide_renderer.py`:
```python
from pathlib import Path
from PIL import Image
from paper2video.types import Scene
from paper2video.renderers.slide import render_slide


def test_render_slide_produces_png_at_target_resolution(tmp_path):
    scene = Scene(
        id=1,
        narration="Hello.",
        visual_type="slide",
        visual_spec={"title": "Test Title", "bullets": ["alpha", "beta", "gamma"]},
        duration_hint_sec=4.0,
    )
    out = render_slide(scene, tmp_path, size=(1920, 1080))
    assert out.exists()
    assert out.suffix == ".png"
    with Image.open(out) as img:
        assert img.size == (1920, 1080)


def test_render_slide_handles_missing_bullets(tmp_path):
    scene = Scene(
        id=2, narration="X", visual_type="slide",
        visual_spec={"title": "Only Title"}, duration_hint_sec=3.0,
    )
    out = render_slide(scene, tmp_path)
    assert out.exists()


def test_render_slide_handles_caption(tmp_path):
    scene = Scene(
        id=3, narration="X", visual_type="slide",
        visual_spec={"title": "T", "bullets": ["b"], "caption": "a caption"},
        duration_hint_sec=3.0,
    )
    out = render_slide(scene, tmp_path)
    assert out.exists()
```

- [ ] **Step 4: Run the test to verify it fails**

```bash
.venv/Scripts/pytest tests/test_slide_renderer.py -v
```
Expected: ImportError.

- [ ] **Step 5: Write the implementation**

`src/paper2video/renderers/slide.py`:
```python
from __future__ import annotations
from pathlib import Path
from ..types import Scene


# 3Blue1Brown-ish palette
BG = "#0f0f1e"
FG = "#f5f5f5"
ACCENT = "#ffc857"


def render_slide(scene: Scene, out_dir: Path, size: tuple[int, int] = (1920, 1080)) -> Path:
    """Render a slide-style scene to a PNG. Pure matplotlib, no LaTeX required."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    width_px, height_px = size
    dpi = 100
    fig = plt.figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()

    # Background
    ax.add_patch(Rectangle((0, 0), 1, 1, facecolor=BG, zorder=0))

    # Accent bar
    ax.add_patch(Rectangle((0.08, 0.82), 0.08, 0.008, facecolor=ACCENT, zorder=1))

    spec = scene.visual_spec or {}
    title = str(spec.get("title", ""))
    bullets = [str(b) for b in spec.get("bullets", []) or []]
    caption = str(spec.get("caption", ""))

    # Title
    ax.text(
        0.08, 0.78, title,
        color=FG, fontsize=52, fontweight="bold",
        ha="left", va="top", wrap=True,
    )

    # Bullets
    for i, b in enumerate(bullets[:6]):
        ax.text(
            0.10, 0.62 - i * 0.09, f"•  {b}",
            color=FG, fontsize=32, ha="left", va="top", wrap=True,
        )

    # Caption
    if caption:
        ax.text(
            0.08, 0.08, caption,
            color=ACCENT, fontsize=24, style="italic", ha="left", va="bottom",
        )

    # Scene number (tiny, bottom right)
    ax.text(
        0.98, 0.04, f"{scene.id:02d}",
        color="#888", fontsize=18, ha="right", va="bottom",
    )

    out_path = out_dir / f"scene_{scene.id:03d}.png"
    fig.savefig(out_path, dpi=dpi, facecolor=BG)
    plt.close(fig)
    return out_path
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
.venv/Scripts/pytest tests/test_slide_renderer.py -v
```
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(renderers): matplotlib slide renderer"
```

---

## Task 8: TTS Module

**Files:**
- Create: `src/paper2video/tts.py`
- Test: `tests/test_tts.py`

Wraps Kokoro behind a `TTSEngine` protocol. Because Kokoro pulls torch, we lazy-import and provide `FakeTTS` that writes a short silent WAV — this lets the full pipeline test run without installing torch.

- [ ] **Step 1: Write the failing test**

`tests/test_tts.py`:
```python
import wave
from pathlib import Path
from paper2video.tts import FakeTTS, synthesize_scene_audio
from paper2video.types import Scene


def test_fake_tts_writes_wav(tmp_path):
    engine = FakeTTS(sample_rate=22050)
    out = engine.synthesize("hello world", tmp_path / "a.wav")
    assert out.exists()
    with wave.open(str(out)) as w:
        assert w.getframerate() == 22050
        assert w.getnframes() > 0


def test_synthesize_scene_audio_returns_path_and_duration(tmp_path):
    engine = FakeTTS()
    scene = Scene(id=1, narration="hi there", visual_type="slide",
                  visual_spec={"title": "t"}, duration_hint_sec=3.0)
    result = synthesize_scene_audio(scene, engine, tmp_path)
    assert result.audio_path.exists()
    assert result.duration_sec > 0


def test_fake_tts_duration_proportional_to_text(tmp_path):
    engine = FakeTTS()
    short = engine.synthesize("hi", tmp_path / "short.wav")
    long = engine.synthesize("this is a much longer sentence with many words", tmp_path / "long.wav")
    with wave.open(str(short)) as s, wave.open(str(long)) as l:
        assert l.getnframes() > s.getnframes()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/pytest tests/test_tts.py -v
```
Expected: ImportError.

- [ ] **Step 3: Write the implementation**

`src/paper2video/tts.py`:
```python
from __future__ import annotations
import struct
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from .types import Scene


class TTSEngine(Protocol):
    sample_rate: int
    def synthesize(self, text: str, out_path: Path) -> Path: ...


@dataclass
class SceneAudio:
    scene_id: int
    audio_path: Path
    duration_sec: float


class FakeTTS:
    """Silent WAV generator for tests. Duration scales with text length."""

    def __init__(self, sample_rate: int = 22050):
        self.sample_rate = sample_rate

    def synthesize(self, text: str, out_path: Path) -> Path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # ~4 chars per 0.1 second, minimum 0.5 seconds
        duration_sec = max(0.5, len(text) / 40.0)
        n_frames = int(duration_sec * self.sample_rate)
        silence = struct.pack("<h", 0) * n_frames
        with wave.open(str(out_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.sample_rate)
            w.writeframes(silence)
        return out_path


class KokoroTTS:
    """Kokoro-82M (Apache 2.0, ~4.2 MOS). Lazy-imports torch/kokoro."""

    def __init__(self, voice: str = "af_heart", lang_code: str = "a"):
        from kokoro import KPipeline  # type: ignore
        self._pipeline = KPipeline(lang_code=lang_code)
        self.voice = voice
        self.sample_rate = 24000

    def synthesize(self, text: str, out_path: Path) -> Path:
        import numpy as np
        import soundfile as sf  # type: ignore

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        chunks: list[np.ndarray] = []
        for _, _, audio in self._pipeline(text, voice=self.voice):
            chunks.append(audio)
        if not chunks:
            audio_full = np.zeros(int(self.sample_rate * 0.5), dtype=np.float32)
        else:
            audio_full = np.concatenate(chunks).astype(np.float32)
        sf.write(str(out_path), audio_full, self.sample_rate)
        return out_path


def _wav_duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / float(w.getframerate())


def synthesize_scene_audio(scene: Scene, engine: TTSEngine, out_dir: Path) -> SceneAudio:
    out_dir = Path(out_dir)
    path = out_dir / f"scene_{scene.id:03d}.wav"
    engine.synthesize(scene.narration, path)
    return SceneAudio(scene_id=scene.id, audio_path=path, duration_sec=_wav_duration(path))
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/pytest tests/test_tts.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(tts): TTSEngine protocol with Fake + Kokoro impls"
```

---

## Task 9: Assembly

**Files:**
- Create: `src/paper2video/assemble.py`
- Test: `tests/test_assemble.py`

Combines per-scene PNGs + per-scene WAVs into one MP4 via ffmpeg. Strategy: build one clip per scene (image + audio, image held for audio duration), then concat with ffmpeg concat demuxer.

- [ ] **Step 1: Write the failing test**

`tests/test_assemble.py`:
```python
import shutil
import subprocess
from pathlib import Path
import pytest
from paper2video.assemble import build_concat_list, assemble_video
from paper2video.tts import FakeTTS, synthesize_scene_audio
from paper2video.renderers.slide import render_slide
from paper2video.types import Scene

FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")


def test_build_concat_list_format(tmp_path):
    lines = build_concat_list([tmp_path / "a.mp4", tmp_path / "b.mp4"])
    assert "file '" in lines
    assert "a.mp4" in lines
    assert "b.mp4" in lines


def test_assemble_video_produces_mp4(tmp_path):
    scenes = [
        Scene(id=1, narration="first scene", visual_type="slide",
              visual_spec={"title": "One", "bullets": ["a"]}, duration_hint_sec=3.0),
        Scene(id=2, narration="second scene", visual_type="slide",
              visual_spec={"title": "Two", "bullets": ["b"]}, duration_hint_sec=3.0),
    ]
    # Render visuals
    img_dir = tmp_path / "img"
    images = [render_slide(s, img_dir) for s in scenes]
    # Render audio
    audio_dir = tmp_path / "audio"
    engine = FakeTTS()
    audios = [synthesize_scene_audio(s, engine, audio_dir) for s in scenes]
    durations = [a.duration_sec for a in audios]

    out = assemble_video(
        images=images,
        audio_paths=[a.audio_path for a in audios],
        durations=durations,
        out_path=tmp_path / "final.mp4",
        work_dir=tmp_path / "work",
    )
    assert out.exists()
    assert out.stat().st_size > 0
    # Probe with ffprobe if available — otherwise just check file size
    probe = shutil.which("ffprobe")
    if probe:
        res = subprocess.run(
            [probe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(out)],
            capture_output=True, text=True, check=True,
        )
        total = float(res.stdout.strip())
        assert total > sum(durations) - 0.5
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/pytest tests/test_assemble.py -v
```
Expected: ImportError (or skipped if ffmpeg missing — in which case install ffmpeg first).

- [ ] **Step 3: Write the implementation**

`src/paper2video/assemble.py`:
```python
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path


class FFmpegNotFound(RuntimeError):
    pass


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise FFmpegNotFound(
            "ffmpeg not found on PATH. Install: `winget install Gyan.FFmpeg` (Win) "
            "or `brew install ffmpeg` (macOS) or `apt install ffmpeg` (Linux)."
        )
    return path


def build_concat_list(clip_paths: list[Path]) -> str:
    """Produce contents of an ffmpeg concat demuxer file."""
    lines = []
    for p in clip_paths:
        abs_posix = Path(p).resolve().as_posix()
        lines.append(f"file '{abs_posix}'")
    return "\n".join(lines) + "\n"


def _build_scene_clip(
    image_path: Path,
    audio_path: Path,
    duration_sec: float,
    out_path: Path,
    width: int,
    height: int,
    fps: int,
) -> Path:
    ffmpeg = _ffmpeg()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-loop", "1", "-i", str(image_path),
        "-i", str(audio_path),
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-r", str(fps),
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
               f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "-t", f"{duration_sec:.3f}",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


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
    ffmpeg = _ffmpeg()
    out_path = Path(out_path)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    clip_paths: list[Path] = []
    for i, (img, aud, dur) in enumerate(zip(images, audio_paths, durations), start=1):
        clip_path = work_dir / f"clip_{i:03d}.mp4"
        _build_scene_clip(img, aud, dur, clip_path, width, height, fps)
        clip_paths.append(clip_path)

    concat_file = work_dir / "concat.txt"
    concat_file.write_text(build_concat_list(clip_paths), encoding="utf-8")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path
```

- [ ] **Step 4: Install ffmpeg if the test was skipped**

```bash
winget install Gyan.FFmpeg
# then restart shell so PATH picks it up
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
.venv/Scripts/pytest tests/test_assemble.py -v
```
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(assemble): ffmpeg scene-clip + concat assembly"
```

---

## Task 10: Pipeline Orchestrator

**Files:**
- Create: `src/paper2video/pipeline.py`
- Test: `tests/test_pipeline.py`

Ties everything together. Takes a URL or file, runs all stages, writes stage outputs to `out/<run_id>/`, returns the final video path.

- [ ] **Step 1: Write the failing test**

`tests/test_pipeline.py`:
```python
import shutil
from pathlib import Path
import pytest
from paper2video.pipeline import run_pipeline, PipelineConfig
from paper2video.llm import FakeLLMClient
from paper2video.tts import FakeTTS
from paper2video.ingest import IngestedDoc

FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")


def test_run_pipeline_end_to_end(tmp_path, monkeypatch):
    # Stub ingest to avoid network
    fake_doc = IngestedDoc(
        text="LLMs can build persistent wikis as an alternative to RAG.",
        title="LLM Wikis",
        source_url="https://example.com/a",
    )
    monkeypatch.setattr("paper2video.pipeline.extract_from_url", lambda url: fake_doc)

    llm = FakeLLMClient(responses=[
        # research: concepts
        '["LLM", "wiki", "RAG"]',
        # research: synthesis
        '{"notes": [], "key_points": ["LLMs can maintain wikis", "RAG has limits"]}',
        # script
        """{
          "title": "LLMs as Wiki Builders",
          "summary": "s",
          "scenes": [
            {"id": 1, "narration": "Welcome.", "visual_type": "slide",
             "visual_spec": {"title": "Intro", "bullets": ["a"]}, "duration_hint_sec": 3.0},
            {"id": 2, "narration": "Thanks.", "visual_type": "slide",
             "visual_spec": {"title": "Outro", "bullets": ["b"]}, "duration_hint_sec": 3.0}
          ]
        }"""
    ])

    cfg = PipelineConfig(
        out_dir=tmp_path / "out",
        run_id="test_run",
        enable_search=False,
    )
    result = run_pipeline(
        "https://example.com/a",
        cfg,
        llm=llm,
        tts=FakeTTS(),
    )
    assert result.video_path.exists()
    assert result.video_path.suffix == ".mp4"
    # Stage outputs should be persisted for debugging
    run_dir = tmp_path / "out" / "test_run"
    assert (run_dir / "ingest.json").exists()
    assert (run_dir / "research.json").exists()
    assert (run_dir / "script.json").exists()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/pytest tests/test_pipeline.py -v
```
Expected: ImportError.

- [ ] **Step 3: Write the implementation**

`src/paper2video/pipeline.py`:
```python
from __future__ import annotations
import json
import time
from dataclasses import dataclass, field, asdict
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
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/pytest tests/test_pipeline.py -v
```
Expected: 1 passed (or skipped if ffmpeg missing).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(pipeline): end-to-end orchestrator with stage outputs"
```

---

## Task 11: CLI

**Files:**
- Create: `src/paper2video/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
from paper2video.cli import build_parser


def test_parser_accepts_url():
    p = build_parser()
    args = p.parse_args(["https://example.com/a"])
    assert args.source == "https://example.com/a"
    assert args.no_search is False


def test_parser_flags():
    p = build_parser()
    args = p.parse_args(["a.pdf", "--no-search", "--fake-tts", "--out", "custom"])
    assert args.no_search is True
    assert args.fake_tts is True
    assert args.out == "custom"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/pytest tests/test_cli.py -v
```
Expected: ImportError.

- [ ] **Step 3: Write the implementation**

`src/paper2video/cli.py`:
```python
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
    load_dotenv()
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
    print(f"✓ video: {result.video_path}")
    print(f"✓ run dir: {result.run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/pytest tests/test_cli.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Run the full test suite**

```bash
.venv/Scripts/pytest -v
```
Expected: all tests pass (some assembly/pipeline tests may skip if ffmpeg isn't installed).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(cli): paper2video command-line entry point"
```

---

## Task 12: Smoke Test — Karpathy Gist

**Files:** (none — this is a verification task)

- [ ] **Step 1: Install optional TTS deps**

```bash
.venv/Scripts/pip install -e ".[tts]"
```

If this fails on Windows (kokoro may need espeak-ng), proceed with `--fake-tts` below.

- [ ] **Step 2: Verify ffmpeg is on PATH**

```bash
ffmpeg -version
```
Expected: version string. If not found, `winget install Gyan.FFmpeg` and restart shell.

- [ ] **Step 3: Set up env**

```bash
cp .env.example .env
# then edit .env to set ANTHROPIC_API_KEY
```

- [ ] **Step 4: Run the pipeline against Karpathy's gist**

```bash
.venv/Scripts/paper2video https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f --no-search --fake-tts --run-id karpathy_smoke
```

Expected: finishes without errors, prints path to `out/karpathy_smoke/video.mp4`. Play it — audio will be silent (FakeTTS), visuals should show the scene slides.

- [ ] **Step 5: Full run with real TTS and search (if deps installed)**

```bash
.venv/Scripts/paper2video https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f --run-id karpathy_full
```

Expected: `out/karpathy_full/video.mp4` — a ~2-3 minute narrated explainer.

- [ ] **Step 6: Inspect and commit the run outputs (excluded via .gitignore, so just note the result)**

```bash
ls out/karpathy_smoke/
# Should contain: ingest.json research.json script.json images/ audio/ work/ video.mp4
```

---

## Future Work (not in this plan)

- **Task 13 (stretch): Manim renderer.** Add `src/paper2video/renderers/manim_r.py` that takes a `visual_spec` with `{"kind": "manim", "code": "..."}` or `{"kind": "equation", "latex": "..."}` and renders via Manim CE. Falls back to slide renderer on render failure. Requires LaTeX.
- **Task 14 (stretch): Script critic loop.** Add a second LLM pass that critiques the draft script ("would a smart novice follow this?") and regenerates weak scenes.
- **Task 15 (stretch): Subtitles.** Add a step that runs `faster-whisper` on the final audio to emit `.srt` and burn it into the video.
- **Task 16 (stretch): Web UI.** A `streamlit` page that takes a URL, shows progress per stage, previews each scene, lets you edit the script before rendering.
