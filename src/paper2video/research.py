from __future__ import annotations
from dataclasses import dataclass
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
