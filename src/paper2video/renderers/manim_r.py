"""Manim-based scene renderer.

Flow:
  1. Ask the LLM to generate a Manim Scene class for a given description + duration.
  2. Write the code to a temp .py file and invoke the manim CLI.
  3. On failure, feed stderr back to the LLM and retry up to `max_retries` times.
  4. Return the path to the rendered mp4 (silent video).
"""
from __future__ import annotations
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

from ..llm import LLMClient
from ..types import Scene


CODEGEN_SYSTEM = """You are an expert Manim Community Edition (v0.18+) animation programmer.
You write short, reliable Manim scene classes that render without errors.

HARD RULES — violating any of these will break the pipeline:
1. Output ONLY Python code. No prose. No markdown code fences. No explanation.
2. The file must define exactly one class named `MainScene` that inherits from `Scene`.
3. Import only from `manim`. Do not import numpy, scipy, or anything else.
4. DO NOT use Tex, MathTex, or anything requiring LaTeX. Use `Text` and `MarkupText` only.
5. DO NOT use external assets (SVG, images, fonts) — only built-in Manim objects.
6. The total animation wall-clock duration must be approximately {duration:.1f} seconds.
   Use `run_time=` on `self.play(...)` and `self.wait(...)` to pace the scene.
7. Use a dark background (Manim's default) with light text. Good colors: WHITE, YELLOW, BLUE, GREEN, RED, GREY_A.
8. Animations should feel like 3Blue1Brown: smooth transforms, progressive reveals,
   highlights, arrows, diagrams. NOT a static slide with a title and bullets.

=== ENTRANCE-POSITIONING RULE — CRITICAL ===

This is the single most common bug in LLM-written Manim code. READ CAREFULLY.

`FadeIn(obj, shift=vec)` does NOT move the object to some target position. It is purely a
RELATIVE animation: the object starts at `(current_position - vec)` and ends at
`(current_position)`. Before the animation runs, wherever `obj` is in the scene graph IS
where it will be after the fade-in.

WRONG PATTERN — do not do this:

    grid = VGroup(box_a, box_b, box_c, box_d)
    grid.arrange_in_grid(rows=2, cols=2)
    grid.move_to(ORIGIN)

    # WRONG: pre-shift each box away, then try to "fly them back" with FadeIn
    box_a.shift(UP * 2 + LEFT * 2)
    box_b.shift(UP * 2 + RIGHT * 2)
    box_c.shift(DOWN * 2 + LEFT * 2)
    box_d.shift(DOWN * 2 + RIGHT * 2)

    self.play(
        FadeIn(box_a, shift=DOWN + RIGHT),  # this does NOT undo the pre-shift!
        FadeIn(box_b, shift=DOWN + LEFT),
        FadeIn(box_c, shift=UP + RIGHT),
        FadeIn(box_d, shift=UP + LEFT),
    )
    # Result: boxes end up far from the grid center, overlapping the title.

CORRECT PATTERN #1 — leave everything at its final grid position, then reveal:

    grid = VGroup(box_a, box_b, box_c, box_d)
    grid.arrange_in_grid(rows=2, cols=2, buff=0.6)
    grid.move_to(ORIGIN)

    # Small shift vectors for flavor — objects still END at grid position
    self.play(
        FadeIn(box_a, shift=DOWN * 0.3),
        FadeIn(box_b, shift=DOWN * 0.3),
        FadeIn(box_c, shift=DOWN * 0.3),
        FadeIn(box_d, shift=DOWN * 0.3),
        lag_ratio=0.1,
        run_time=1.2,
    )

CORRECT PATTERN #2 — use .animate.move_to(target) if you want explicit travel:

    grid = VGroup(box_a, box_b, box_c, box_d).arrange_in_grid(rows=2, cols=2, buff=0.6)
    grid.move_to(ORIGIN)
    # Capture grid positions BEFORE moving boxes away
    targets = [b.get_center() for b in grid]

    # Move boxes to start positions (off-screen corners, center, wherever)
    box_a.move_to(ORIGIN)
    box_b.move_to(ORIGIN)
    box_c.move_to(ORIGIN)
    box_d.move_to(ORIGIN)

    self.play(
        box_a.animate.move_to(targets[0]),
        box_b.animate.move_to(targets[1]),
        box_c.animate.move_to(targets[2]),
        box_d.animate.move_to(targets[3]),
        run_time=1.0,
    )

CORRECT PATTERN #3 — simplest of all, just use GrowFromCenter / GrowFromPoint:

    self.play(
        GrowFromCenter(box_a),
        GrowFromCenter(box_b),
        GrowFromCenter(box_c),
        GrowFromCenter(box_d),
        lag_ratio=0.1,
        run_time=1.2,
    )

THE RULE: after you arrange/position objects, DO NOT manually `.shift()` them away before
animating them in. If you need the animation to show motion, use pattern #2 (explicit
animate.move_to) or pattern #3 (Grow). NEVER use FadeIn(shift=vec) to compensate for a
manual .shift() — those don't cancel.

=== END ENTRANCE-POSITIONING RULE ===

=== SCALE RULE — CRITICAL ===

DO NOT use `.scale(factor)` with factor less than 0.5 or greater than 2.0.
DO NOT use `.animate.scale(factor)` with factor less than 0.5 or greater than 2.0.

Why: compounding scale calls across animation steps produces sizing bugs that make text
unreadable. E.g., calling `.scale(0.1)` then `.animate.scale(10)` does NOT return the
object to its original size — it leaves it at 10% of the original. Small scale factors
also compound when applied to VGroups containing text, making labels become invisible pt
sizes like 2.4pt.

INSTEAD, use these patterns for entrances and exits:

- Entrance (fade in):                  self.play(FadeIn(obj), run_time=1)
- Entrance (slide in from left):       self.play(FadeIn(obj, shift=RIGHT * 1.5), run_time=1)
- Entrance (drop from above):          self.play(FadeIn(obj, shift=DOWN * 1.5), run_time=1)
- Entrance (grow from center):         self.play(GrowFromCenter(obj), run_time=1)
- Emphasis (small pulse):              self.play(Indicate(obj, scale_factor=1.1), run_time=0.8)
- Emphasis (flash color):              self.play(Flash(obj, color=YELLOW), run_time=0.5)
- Exit (mid-scene cleanup):            self.play(FadeOut(obj), run_time=0.6)
- Transform one thing to another:      self.play(ReplacementTransform(a, b), run_time=1)

The only ACCEPTABLE use of .scale() is a tiny polish like .scale(1.1) or .scale(0.9) for
a subtle emphasis, NEVER for building an entrance/exit animation.

Do NOT compose .scale() with .animate.scale() expecting them to cancel out. They don't.

=== END SCALE RULE ===

=== ENDING RULE — CRITICAL ===

NEVER end the scene with FadeOut, Uncreate, Unwrite, or any disappearance animation.
NEVER call self.play(FadeOut(...)) as your last animation.
The final visual composition MUST remain on screen at the end of the scene.

Why: the pipeline freezes the last frame and holds it to match the narration audio length.
If you fade everything out, the held frame is black, and the viewer stares at a black screen
while the narrator is still talking. This is a critical bug.

Correct ending pattern: after all your animations, use `self.wait(N)` where N is sized so
the total scene duration matches the target. Leave the diagram on screen.
DO NOT clean up. DO NOT fade out. Just wait. The next scene will cut in cleanly.

=== END ENDING RULE ===

=== SAFE AREA — CRITICAL, READ TWICE ===

Manim's frame is exactly 14.22 units wide and 8.0 units tall, centered at ORIGIN.
That means visible coordinates run from x=-7.11 to x=+7.11 and y=-4.0 to y=+4.0.

You MUST keep ALL visible content inside a SAFE AREA of:
   width  ≤ 12.0 units  (so x stays between -6.0 and +6.0)
   height ≤ 6.5 units   (so y stays between -3.25 and +3.25)

THE NUMBER ONE BUG TO AVOID:
`scale_to_fit_width` and `scale_to_fit_height` scale UP as well as down. If you call
`Text("Hi", font_size=48).scale_to_fit_width(10)` on text that is naturally 3 units wide,
Manim will MULTIPLY its size by 3.3x and you get a giant 10-unit-wide title that fills the
whole screen. NEVER use `scale_to_fit_width` or `scale_to_fit_height` directly on Text.

INSTEAD, use this helper pattern. ALWAYS define `fit` at the top of construct() and use it:

    def fit(mobj, max_w=11.0, max_h=6.0):
        # Only shrinks, never enlarges.
        s = min(max_w / mobj.width, max_h / mobj.height, 1.0)
        if s < 1.0:
            mobj.scale(s)
        return mobj

Then use `fit(title)` and `fit(diagram)` instead of `scale_to_fit_width`.

Mandatory patterns to keep things in bounds:

(a) Pick font sizes DIRECTLY. Do not rely on auto-scaling. Safe values:
        - Big title (1-3 short words):  font_size=56
        - Normal title:                  font_size=44
        - Subtitle / scene heading:      font_size=36
        - Body text, labels in diagrams: font_size=28
        - Small caption text:            font_size=22

(b) Long titles must wrap or be shrunk. After creating, ALWAYS run through fit():
        title = Text("A Knowledge Base That Compounds", font_size=44)
        fit(title, max_w=11.5)
        title.to_edge(UP, buff=0.6)

(c) Build diagrams with VGroup + .arrange(), then fit() the whole group, then move_to(ORIGIN):
        row = VGroup(box_a, box_b, box_c).arrange(RIGHT, buff=1.0)
        fit(row, max_w=11.0, max_h=4.5)
        row.move_to(ORIGIN)

(d) DO NOT call `.shift(DOWN * 3)` or any shift larger than 2 units AFTER positioning a
    group. If a group is at ORIGIN and you shift it DOWN*4, it goes off the bottom of the
    frame. Use .next_to() or .arrange() with buff to control spacing instead.

(e) For a title-on-top + diagram-in-middle layout, use a single VGroup:
        layout = VGroup(title, diagram).arrange(DOWN, buff=0.6)
        fit(layout, max_w=12.0, max_h=6.5)
        layout.move_to(ORIGIN)

(f) buff>=0.6 in .to_edge() and .arrange() to keep margins.

=== END SAFE AREA ===

Available Manim primitives you should use liberally:
- Text, MarkupText (for rich text)
- Circle, Square, Rectangle, RoundedRectangle, Line, Arrow, DoubleArrow, Dot
- VGroup (group and position multiple objects)
- Create, Write, FadeIn, FadeOut, Transform, ReplacementTransform, Indicate, Flash
- .move_to, .next_to, .scale, .arrange(direction, buff=...), .to_edge(direction, buff=...)
- UP, DOWN, LEFT, RIGHT, ORIGIN, UL, UR, DL, DR
- self.play(anim1, anim2, run_time=2)
- self.wait(1)

Worked example of a SAFE scene structure — COPY THIS PATTERN:

    from manim import *

    class MainScene(Scene):
        def construct(self):
            def fit(mobj, max_w=11.0, max_h=6.0):
                s = min(max_w / mobj.width, max_h / mobj.height, 1.0)
                if s < 1.0:
                    mobj.scale(s)
                return mobj

            title = Text("The Wiki Pattern", font_size=44)
            fit(title, max_w=11.0)
            title.to_edge(UP, buff=0.6)

            box_a = RoundedRectangle(width=2.6, height=1.4, color=BLUE)
            box_b = RoundedRectangle(width=2.6, height=1.4, color=GREEN)
            box_c = RoundedRectangle(width=2.6, height=1.4, color=YELLOW)
            label_a = Text("SOURCES", font_size=24).move_to(box_a)
            label_b = Text("WIKI", font_size=24).move_to(box_b)
            label_c = Text("SCHEMA", font_size=24).move_to(box_c)
            group_a = VGroup(box_a, label_a)
            group_b = VGroup(box_b, label_b)
            group_c = VGroup(box_c, label_c)

            row = VGroup(group_a, group_b, group_c).arrange(RIGHT, buff=1.0)
            fit(row, max_w=11.0, max_h=4.0)
            row.move_to(ORIGIN)

            self.play(Write(title), run_time=1.5)
            self.play(FadeIn(group_a, shift=UP*0.3), run_time=1)
            self.play(FadeIn(group_b, shift=UP*0.3), run_time=1)
            self.play(FadeIn(group_c, shift=UP*0.3), run_time=1)
            self.wait(1)

Notice: `fit` is defined inside construct(), every text has an explicit reasonable
font_size, the diagram is grouped + arranged + fit + moved to ORIGIN. NO arbitrary shifts.
Your output MUST follow this structure.
"""

PORTRAIT_ADDENDUM = """

=== PORTRAIT MODE (9:16 VERTICAL VIDEO) ===

This scene will be rendered at 1080x1920 (portrait / vertical), NOT landscape.
Manim's frame is still 14.22 x 8.0 units, but the RENDER will stretch it to 9:16.
This means:
- Horizontal space is VERY limited. Keep everything narrow (max_w=7.0 in fit()).
- Vertical space is generous. Stack elements vertically with .arrange(DOWN, buff=0.8).
- Title should be at font_size=36, body at font_size=24.
- Use VGroup(...).arrange(DOWN, ...) and fit(group, max_w=7.0, max_h=6.0) for layouts.
- Avoid placing elements past x=±3.5 — they WILL be cut off in portrait render.
- The frame center is still ORIGIN. Think of a tall, narrow column of content.
- Prefer fewer, larger elements stacked vertically over wide horizontal layouts.

=== END PORTRAIT MODE ===
"""

CODEGEN_USER = """Generate a Manim scene for scene {scene_id} of an explainer video.

NARRATION (this is what the viewer hears — your animation must illustrate it):
\"\"\"
{narration}
\"\"\"

VISUAL DIRECTION:
{visual_direction}

TARGET DURATION: {duration:.1f} seconds

Write a complete Python file defining `class MainScene(Scene)`. Output code only.
"""

RETRY_USER = """Your previous Manim code failed to render. Fix it.

PREVIOUS CODE:
```python
{previous_code}
```

ERROR OUTPUT (last 60 lines):
```
{error_tail}
```

Output the fully corrected code only. No explanation. No fences. Remember the HARD RULES.
"""

LINT_RETRY_USER = """Your previous Manim code failed our static safety checks. Fix it.

PREVIOUS CODE:
```python
{previous_code}
```

LINT ERRORS:
{lint_errors}

Output the fully corrected code only. No explanation. No fences.
Remember: define `fit(mobj, max_w, max_h)` inside construct() and use it instead of
scale_to_fit_width/scale_to_fit_height. Pick explicit reasonable font sizes (44 for titles,
28 for body). Never .shift() by more than 2 units.
"""


@dataclass
class ManimRenderError(Exception):
    message: str
    stderr: str
    last_code: str

    def __str__(self) -> str:
        return self.message


def lint_manim_code(code: str) -> list[str]:
    """Static checks against the patterns we know cause cutoffs and render failures.

    Returns a list of error messages. Empty list means the code passed lint.
    """
    errors: list[str] = []
    lines = code.splitlines()

    # 1. Must define MainScene
    if "class MainScene" not in code:
        errors.append("Missing `class MainScene(Scene):` — the entry point.")

    # 2. Must not use Tex/MathTex (LaTeX dependency)
    for i, line in enumerate(lines, start=1):
        stripped = line.split("#", 1)[0]  # ignore comments
        if "MathTex(" in stripped or "Tex(" in stripped and "Text(" not in stripped:
            errors.append(f"Line {i}: uses Tex/MathTex which requires LaTeX. Use Text() instead.")

    # 3. CRITICAL: scale_to_fit_width / scale_to_fit_height called directly on text-like
    #    objects scales them UP if they're smaller than the target. We forbid these calls
    #    entirely; the code should use the fit() helper instead.
    for i, line in enumerate(lines, start=1):
        stripped = line.split("#", 1)[0]
        if "scale_to_fit_width" in stripped or "scale_to_fit_height" in stripped:
            errors.append(
                f"Line {i}: uses scale_to_fit_width/height which can ENLARGE small objects "
                f"and cause cutoff. Use the fit() helper instead — it only shrinks."
            )

    # 4. Must define a `fit` helper inside construct() (or not call it at all).
    if "fit(" in code and "def fit(" not in code:
        errors.append("Code calls fit(...) but never defines `def fit(mobj, ...):` inside construct().")

    # 5. Catch arbitrary large shifts applied to initial-state objects.
    #    Pattern: `.shift(...)` that is NOT inside `.animate.shift(...)`, with any
    #    magnitude >= 1.5 on any direction. Large initial shifts are almost always
    #    a "fly in from corner" anti-pattern the LLM can't compensate for later.
    import re
    shift_call = re.compile(r"(?<!animate)\.shift\s*\(([^)]*)\)")
    magnitude_token = re.compile(r"(?:UP|DOWN|LEFT|RIGHT|UL|UR|DL|DR)\s*\*\s*(\d+(?:\.\d+)?)")
    for i, line in enumerate(lines, start=1):
        stripped = line.split("#", 1)[0]
        for call in shift_call.finditer(stripped):
            args = call.group(1)
            magnitudes = [float(m.group(1)) for m in magnitude_token.finditer(args)]
            if magnitudes and max(magnitudes) >= 1.5:
                errors.append(
                    f"Line {i}: .shift() with magnitude >= 1.5 on an initial-state object. "
                    f"This is the 'fly in from corner' anti-pattern — FadeIn(shift=...) will "
                    f"NOT move the object back to a grid position. Use .animate.move_to(target) "
                    f"for explicit travel, or leave the object at its final position and use "
                    f"FadeIn(obj, shift=SMALL_VECTOR) for a subtle reveal."
                )
                break

    # 6. Must not import anything other than from manim
    for i, line in enumerate(lines, start=1):
        s = line.strip()
        if s.startswith("import ") or s.startswith("from "):
            if not (s.startswith("from manim") or s == "from manim import *"):
                errors.append(f"Line {i}: forbidden import. Only `from manim import *` is allowed.")

    # 7a. No dangerous .scale(factor) calls — causes unreadable text from compounding.
    scale_pattern = re.compile(r"\.(?:animate\.)?scale\s*\(\s*(-?\d+(?:\.\d+)?)\s*[,)]")
    for i, line in enumerate(lines, start=1):
        stripped = line.split("#", 1)[0]
        for m in scale_pattern.finditer(stripped):
            factor = float(m.group(1))
            if factor < 0.5 or factor > 2.0:
                errors.append(
                    f"Line {i}: .scale({factor}) outside the allowed range [0.5, 2.0]. "
                    f"Compounding scales produce unreadable text. Use FadeIn(shift=...), "
                    f"GrowFromCenter(), or ReplacementTransform() for entrances/exits "
                    f"instead of shrink-and-grow tricks."
                )
                break

    # 7b. Last animation must not be a disappearance — pipeline freezes last frame.
    #    Find all self.play(...) calls and check that the LAST one doesn't fade things out.
    play_indices = [i for i, line in enumerate(lines) if "self.play(" in line]
    if play_indices:
        last_play_line = play_indices[-1]
        # Collect lines until matching closing paren — naive, but enough for our case
        chunk = []
        depth = 0
        for j in range(last_play_line, min(len(lines), last_play_line + 30)):
            chunk.append(lines[j])
            depth += lines[j].count("(") - lines[j].count(")")
            if depth <= 0 and j > last_play_line:
                break
        chunk_text = "\n".join(chunk)
        forbidden_endings = ["FadeOut(", "Uncreate(", "Unwrite("]
        for token in forbidden_endings:
            if token in chunk_text:
                errors.append(
                    f"Line {last_play_line + 1}: last self.play() uses {token.rstrip('(')} — "
                    f"the scene must NOT fade out at the end. Pipeline freezes the final "
                    f"frame to match audio length, so fading out leaves the viewer staring "
                    f"at black. End with self.wait(N) instead and leave content on screen."
                )
                break

    return errors


def _strip_code_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        # Remove opening fence (```python or ```)
        first_nl = raw.find("\n")
        if first_nl != -1:
            raw = raw[first_nl + 1 :]
        if raw.endswith("```"):
            raw = raw[: -3]
    return raw.strip()


def _run_manim(
    code_file: Path,
    out_media_dir: Path,
    quality: str = "l",
    resolution: tuple[int, int] | None = None,
) -> tuple[int, str, Path | None]:
    """Invoke the manim CLI. Returns (returncode, stderr_tail, rendered_mp4_or_None)."""
    # Quality flags: -ql=low 480p15, -qm=medium 720p30, -qh=high 1080p60
    cmd = [
        sys.executable, "-m", "manim",
        f"-q{quality}",
        "--disable_caching",
        "--media_dir", str(out_media_dir),
        "--output_file", "MainScene",
    ]
    if resolution:
        cmd.extend(["--resolution", f"{resolution[0]},{resolution[1]}"])
    cmd.extend([str(code_file), "MainScene"])
    proc = subprocess.run(cmd, capture_output=True, text=True)
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    tail = "\n".join(combined.strip().splitlines()[-60:])

    # Find the rendered MP4 — Manim writes to:
    #   <media_dir>/videos/<script_stem>/<quality_dir>/MainScene.mp4
    # The quality_dir naming depends on the flags:
    #   -ql → 480p15, -qm → 720p30, -qh → 1080p60, -qk → 2160p60
    #   --resolution W,H → uses Hp{fps} format, e.g. --resolution 1080,1920 → "1920p30"
    quality_dirs = {"l": "480p15", "m": "720p30", "h": "1080p60", "k": "2160p60"}
    videos_dir = out_media_dir / "videos" / code_file.stem

    # Build a prioritized list of possible directory names
    candidate_dirs = []
    if resolution:
        # Manim names it "{height}p{fps}" for custom resolution
        fps_guess = 30 if quality in ("m", "h") else 15 if quality == "l" else 60
        candidate_dirs.append(f"{resolution[1]}p{fps_guess}")
        candidate_dirs.append(f"{resolution[0]}x{resolution[1]}")
    candidate_dirs.append(quality_dirs.get(quality, "480p15"))

    rendered = None
    for qdir in candidate_dirs:
        p = videos_dir / qdir / "MainScene.mp4"
        if p.exists():
            rendered = p
            break

    # Last resort: glob for any MainScene.mp4 under the videos dir
    if rendered is None and proc.returncode == 0:
        hits = list(videos_dir.glob("*/MainScene.mp4"))
        if hits:
            rendered = hits[0]

    if proc.returncode == 0 and rendered is not None:
        return 0, tail, rendered
    return proc.returncode or 1, tail, None


def _compose_visual_direction(spec: dict) -> str:
    """Turn a scene's visual_spec into a compact instruction block for the code-gen LLM."""
    parts = []
    if "title" in spec:
        parts.append(f"Title/heading: {spec['title']}")
    if "direction" in spec:
        parts.append(f"Animation direction: {spec['direction']}")
    if "elements" in spec:
        parts.append(f"Elements to show: {', '.join(spec['elements'])}")
    if "bullets" in spec and spec["bullets"]:
        parts.append("Points to emphasize (animate them in progressively, do not just list):")
        for b in spec["bullets"]:
            parts.append(f"  - {b}")
    if "caption" in spec:
        parts.append(f"Closing beat: {spec['caption']}")
    return "\n".join(parts) if parts else "(no specific direction — invent something illustrative)"


def render_manim_scene(
    scene: Scene,
    duration_sec: float,
    out_dir: Path,
    llm: LLMClient,
    quality: str = "m",
    max_retries: int = 3,
    resolution: tuple[int, int] | None = None,
) -> Path:
    """Generate and render a Manim scene, retrying on failure.

    Args:
        resolution: Optional (width, height) in pixels. If portrait (e.g. 1080x1920),
            the system prompt is adapted for vertical layout and manim is invoked
            with --resolution.

    Returns the path to the rendered silent MP4.
    Raises ManimRenderError after all retries exhausted.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Resume: if a rendered clip already exists from a previous run, reuse it.
    final = out_dir / f"scene_{scene.id:03d}.mp4"
    if final.exists() and final.stat().st_size > 0:
        return final

    scene_work = out_dir / f"scene_{scene.id:03d}_work"
    scene_work.mkdir(parents=True, exist_ok=True)

    code_file = scene_work / f"scene_{scene.id:03d}.py"
    media_dir = scene_work / "media"

    is_portrait = resolution and resolution[1] > resolution[0]

    visual_direction = _compose_visual_direction(scene.visual_spec or {})
    user_prompt = CODEGEN_USER.format(
        scene_id=scene.id,
        narration=scene.narration,
        visual_direction=visual_direction,
        duration=duration_sec,
    )
    system_prompt = CODEGEN_SYSTEM.format(duration=duration_sec)
    if is_portrait:
        system_prompt += PORTRAIT_ADDENDUM

    last_code = ""
    last_err = ""
    last_lint: list[str] = []
    for attempt in range(max_retries + 1):
        if attempt == 0:
            raw = llm.complete(user_prompt, system=system_prompt)
        elif last_lint:
            retry_prompt = LINT_RETRY_USER.format(
                previous_code=last_code,
                lint_errors="\n".join(f"- {e}" for e in last_lint),
            )
            raw = llm.complete(retry_prompt, system=system_prompt)
        else:
            retry_prompt = RETRY_USER.format(
                previous_code=last_code,
                error_tail=last_err,
            )
            raw = llm.complete(retry_prompt, system=system_prompt)

        code = _strip_code_fences(raw)
        last_code = code
        code_file.write_text(code, encoding="utf-8")

        # Static lint pass first — cheap and catches the obvious bugs.
        lint_errors = lint_manim_code(code)
        if lint_errors:
            last_lint = lint_errors
            last_err = "Lint failed:\n" + "\n".join(lint_errors)
            continue
        last_lint = []

        returncode, err_tail, rendered = _run_manim(code_file, media_dir, quality=quality, resolution=resolution)
        if returncode == 0 and rendered is not None:
            final = out_dir / f"scene_{scene.id:03d}.mp4"
            shutil.copy2(rendered, final)
            return final
        last_err = err_tail

    raise ManimRenderError(
        message=f"Manim render failed for scene {scene.id} after {max_retries + 1} attempts",
        stderr=last_err,
        last_code=last_code,
    )
