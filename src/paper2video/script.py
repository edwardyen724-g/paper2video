from __future__ import annotations
from .llm import LLMClient
from .research import ResearchResult
from .types import Scene, ScriptDoc


SCRIPT_PROMPT = """You are writing the script for a 2-5 minute explainer video in the style of
3Blue1Brown: clear, progressive, and HEAVILY VISUAL. The audience is a smart novice.

CRITICAL: This is NOT a slide deck. Every scene will be rendered as a Manim animation —
shapes moving, text writing in, diagrams being constructed, transforms. You must think in
terms of MOTION and METAPHOR, not titles and bullet points.

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
      "visual_type": "manim",
      "visual_spec": {{
        "title": "optional short label or heading (<=40 chars) — may be empty",
        "direction": "REQUIRED. A concrete, visual description of the animation: what objects appear, how they move, what transforms into what, what the viewer should be LOOKING AT. Write it like a shot description. Use verbs like 'fade in', 'transform into', 'slide from left', 'highlight', 'draw arrow from X to Y'. 2-4 sentences.",
        "elements": ["short list of key visual objects to draw, e.g. 'a green box labeled RAG', 'three stacked rectangles', 'a curved arrow'"],
        "caption": "optional 1-line text callout shown during the scene"
      }},
      "duration_hint_sec": 5.0
    }}
  ]
}}

Constraints:
- 5 to 10 scenes total.
- Each narration 1-3 sentences, spoken English, no jargon without a plain-English gloss.
- Total narration should read in 2-5 minutes (~150 words per minute).
- Every scene must have a non-empty `direction` field describing what ANIMATES.
- Avoid static text-heavy scenes. If a scene would just be "a title and bullets", REDESIGN it
  as something visual — e.g., boxes being connected, an arrow transforming, items being
  grouped into categories, a process flowing step by step.
- Do NOT reference LaTeX, equations, SVGs, or external images — pure Manim shapes + Text only.
- Output JSON only, no prose, no code fences.

Examples of GOOD directions:
- "Three labeled rectangles fade in on the left: SOURCES, WIKI, SCHEMA. Arrows draw between them showing data flow from sources into the wiki, with the schema arrow pointing at the wiki from above. The wiki rectangle pulses yellow to emphasize it as the center."
- "A single box labeled 'QUERY' appears. A magnifying-glass circle sweeps across a field of document rectangles on the right. Then the circle fades and a new answer box writes in at the bottom. The whole process replays faster to show 'every time you ask'."
- "Text 'Ingest' writes in at top. Below it, a file icon slides from the left into an existing wiki diagram. Lines from the new file extend to connect with existing wiki nodes, showing integration."

Examples of BAD directions (DO NOT DO THIS):
- "Show the title and three bullet points"
- "Display a slide with the key concepts"
- "Animate the text appearing"
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
