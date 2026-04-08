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
