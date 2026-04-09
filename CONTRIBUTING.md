# Contributing to paper2video

Issues and PRs welcome. The codebase is small on purpose — read it, change it, don't be precious.

## The core design choice: lint, don't babysit

The Manim renderer has one hard problem: LLMs generate Python that looks fine syntactically but animates incorrectly — boxes fly off-screen, text shrinks to unreadable pt sizes, scenes end with a fade-to-black while the narrator keeps talking. These aren't crashes. They render successfully and look wrong.

**We don't solve this with a post-render quality check.** That would be slow, expensive, and only catches bugs at the very end of the pipeline. Instead:

### When a bad video ships, add a lint rule.

Every bug we've seen so far is a *pattern* the LLM keeps falling into. The fix is always the same shape:

1. Identify the anti-pattern in the generated code (e.g. `.scale(0.1)` followed by `.animate.scale(10)` — doesn't cancel out)
2. Add a regex-level check in `lint_manim_code()` (`src/paper2video/renderers/manim_r.py`) that flags it
3. Write a failing test in `tests/test_manim_renderer.py` — `test_lint_catches_<pattern>`
4. Add explicit guidance to `CODEGEN_SYSTEM` in the same file explaining what's wrong, why, and what to do instead. Include a worked example.
5. Rerun the pipeline on the failing scene and verify the lint catches the retry

The lint loop is very cheap: a regex pass before render, with up to 3 retries where each retry is just another LLM call feeding the lint errors back. An LLM call costs pennies; a bad render wastes seconds of the user's time and looks unprofessional.

### What's already covered

See `lint_manim_code()` for the current rule set. Short list as of v0.1:

- Must define `class MainScene(Scene)`
- No `Tex`/`MathTex` (LaTeX-free install)
- No `scale_to_fit_width`/`scale_to_fit_height` — they enlarge small objects, causing cutoff
- Calls to `fit(...)` require the helper to be defined inside `construct()`
- `.shift(dir * N)` with `N >= 1.5` (outside `.animate.shift()`) — the "fly in from corner" anti-pattern
- Only `from manim` imports allowed
- `.scale(x)` with `x < 0.5` or `x > 2.0` — compounding scale bugs
- The last `self.play()` in a scene must not be `FadeOut`/`Uncreate`/`Unwrite` — pipeline freezes the last frame to match audio length

### What to do when you hit a new class of bug

1. **Don't silently patch the generated code.** That hides the pattern from the next user.
2. **Don't add a runtime post-check.** That's expensive and vague.
3. **Do** add a specific lint rule, a test, and prompt guidance. That makes the fix permanent, testable, and visible.

## Other areas welcoming contributions

- **Renderer backends** — Manim is the main engine, but there's a `Renderer` protocol in `renderers/base.py`. A Remotion-based renderer or a WebGL one would both be fine additions.
- **TTS engines** — Kokoro is the default, but the `TTSEngine` protocol takes any `synthesize(text, path)` callable. XTTS, F5-TTS, Chatterbox wrappers all welcome.
- **LLM backends** — `LLMClient` is a protocol. An Ollama-backed client for fully local runs would make the tool cheaper and more private.
- **Script critic loop** — a second-pass LLM that grades the draft script and rewrites weak scenes. Scoped by scene, not the whole script.
- **Subtitle burning** — run `faster-whisper` on the final audio to emit SRT, burn via ffmpeg.

## Running tests

```bash
.venv/Scripts/python -m pytest -v
```

All 37 tests run offline — no API key needed. They use `FakeLLMClient` and `FakeTTS`.

## Code style

- Python 3.11+
- Type hints encouraged, not required
- No linter enforced yet — run `ruff` if you want
- Keep each module under ~300 lines. If it grows past that, split by responsibility.
