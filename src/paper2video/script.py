from __future__ import annotations
import json
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

SOCIAL_SCRIPT_PROMPT = """You are writing a 45-second vertical social video about a technical article.
Platform: TikTok, Instagram Reels, Xiaohongshu.
Audience: curious builders who are scrolling FAST. You have 6 seconds to hook them.

=== PACING RULES (backed by platform retention data) ===

1. HOOK IN 6 SECONDS. Scene 1 must stop the scroll instantly. Pick ONE of these proven
   hook formulas and adapt it to the article's main insight:

   FORMULA A — Contrarian claim: "[Everyone thinks X]... but actually [surprising opposite]."
     Example: "Everyone says RAG is the future of AI memory... but it forgets everything between questions."

   FORMULA B — Shocking stat or specific number: "[Specific number] that changes everything."
     Example: "80% of AI-generated code passes its own tests — and fails in production."

   FORMULA C — "What if" scenario: "What if [familiar thing] was actually [reframe]?"
     Example: "What if your AI agent grades its own homework... and always gives itself an A?"

   FORMULA D — Direct challenge: "You're doing [common thing] wrong. Here's why."
     Example: "You're building AI agents wrong. Here's what Anthropic figured out."

   FORMULA E — Pattern interrupt: Start mid-thought, as if the viewer walked into a conversation.
     Example: "...so the agent just quit. Halfway through. Said it was done. It wasn't."

   NEVER start with: "In this video", "Today we'll explore", "Let me explain", "Have you ever wondered".
   The hook must feel like a CLAIM, not an introduction.

2. EVERY SCENE IS 8-12 SECONDS. No scene longer than 12 seconds. Viewers drop off after 8s
   of the same visual. If you need more time for an idea, split it into two scenes.

3. SOMETHING MUST CHANGE EVERY 3 SECONDS inside each scene. The animation direction must
   describe at least 2-3 distinct visual beats per scene — elements appearing, transforming,
   highlighting, moving. No static holds longer than 2 seconds.

4. TOTAL VIDEO: 40-50 seconds of narration across 5-6 scenes. Target 45 seconds.
   At ~150 words/minute, that's roughly 100-120 words of total narration.

5. VARIABLE PACING. Scene 1 (hook) is fast — 6-8 seconds. Middle scenes are 8-12 seconds.
   Final scene (payoff) is 8-10 seconds. Don't make every scene the same length.

6. LAST SCENE answers "why should I care?" in one punchy sentence. End on a forward-looking
   statement, not a summary.

7. NARRATION IS SHORT. Each scene gets 1 sentence, max 2 short sentences. Every word must
   earn its place. Cut adjectives. Cut filler. If it reads like a textbook, rewrite it.

=== END PACING RULES ===

INPUT ARTICLE:
{source_text}

KEY POINTS:
{key_points}

RESEARCH NOTES:
{notes}

Produce JSON only with this exact shape:
{{
  "title": "punchy title (max 8 words, no colons)",
  "summary": "one-sentence summary",
  "scenes": [
    {{
      "id": 1,
      "narration": "one short spoken sentence — this is the HOOK",
      "visual_type": "manim",
      "visual_spec": {{
        "title": "2-4 word on-screen title",
        "direction": "REQUIRED: describe 2-3 visual beats that happen during this scene. What appears first, what changes, what the viewer's eye follows. Use verbs: appears, slides, transforms, highlights, connects, pulses. Something must move every 3 seconds.",
        "elements": ["key visual objects"],
        "caption": "optional 1-line callout"
      }},
      "duration_hint_sec": 8.0
    }}
  ]
}}

Rules:
- 5 to 6 scenes. No more, no less.
- Scene 1: hook (6-8 sec). Scenes 2-4/5: explanation (8-12 sec). Last scene: payoff (8-10 sec).
- Total narration ~100-120 words (45 seconds at speaking pace).
- Every direction field must describe multiple visual beats, not a static layout.
- No jargon without a gloss. Plain English only.
- Output JSON only. No prose. No code fences.
"""

SOCIAL_REVISION_PROMPT = """You are revising an existing short-form social video script.

REVISION INSTRUCTION:
{instruction}

CURRENT SCRIPT:
{script_json}

Return JSON only with this exact shape:
{{
  "title": "updated title",
  "summary": "updated summary",
  "changed_scene_ids": [1, 3],
  "scenes": [
    {{
      "id": 1,
      "narration": "updated narration",
      "visual_type": "manim",
      "visual_spec": {{
        "title": "short title",
        "direction": "visual direction",
        "elements": ["a", "b"],
        "caption": "optional"
      }},
      "duration_hint_sec": 8.0
    }}
  ]
}}

Rules:
- Keep unchanged scenes semantically consistent.
- Prefer targeted edits to the hook, pacing, clarity, or layout.
- Output the full updated script, plus changed_scene_ids.
- Output JSON only.
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


def write_social_script(research_result: ResearchResult, llm: LLMClient) -> ScriptDoc:
    notes_str = "\n".join(f"- {n.claim}" for n in research_result.notes) or "(none)"
    key_points_str = "\n".join(f"- {p}" for p in research_result.key_points[:4]) or "(none)"
    raw = llm.complete_json(
        SOCIAL_SCRIPT_PROMPT.format(
            source_text=research_result.source_text[:10000],
            key_points=key_points_str,
            notes=notes_str,
        )
    )
    scenes = [
        Scene(
            id=s.get("id") or i,
            narration=s["narration"],
            visual_type=s.get("visual_type", "manim"),
            visual_spec=s.get("visual_spec", {}),
            duration_hint_sec=float(s.get("duration_hint_sec", 8.0)),
        )
        for i, s in enumerate(raw.get("scenes", []), start=1)
    ]
    return ScriptDoc(
        title=raw.get("title", "Untitled"),
        summary=raw.get("summary", ""),
        scenes=scenes,
    )


def revise_social_script(script_doc: ScriptDoc, instruction: str, llm: LLMClient) -> tuple[ScriptDoc, list[int]]:
    raw = llm.complete_json(
        SOCIAL_REVISION_PROMPT.format(
            instruction=instruction.strip(),
            script_json=json.dumps(script_doc.model_dump(), ensure_ascii=False, indent=2),
        )
    )
    scenes = [
        Scene(
            id=s.get("id") or i,
            narration=s["narration"],
            visual_type=s.get("visual_type", "manim"),
            visual_spec=s.get("visual_spec", {}),
            duration_hint_sec=float(s.get("duration_hint_sec", 8.0)),
        )
        for i, s in enumerate(raw.get("scenes", []), start=1)
    ]
    return (
        ScriptDoc(
            title=raw.get("title", script_doc.title),
            summary=raw.get("summary", script_doc.summary),
            scenes=scenes,
        ),
        [int(scene_id) for scene_id in raw.get("changed_scene_ids", [])],
    )
