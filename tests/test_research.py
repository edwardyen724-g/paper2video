from paper2video.llm import FakeLLMClient
from paper2video.research import research, ResearchResult
from paper2video.ingest import IngestedDoc


def fake_search(query: str, max_results: int = 3):
    return [{"title": f"{query} - result", "url": "https://example.com", "snippet": "snippet"}]


def test_research_identifies_concepts_and_synthesizes():
    doc = IngestedDoc(text="LLMs can build wikis.", title="Wiki", source_url="https://x")
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
