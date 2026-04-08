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
    llm = FakeLLMClient(responses=["""{
      "title": "T", "summary": "S",
      "scenes": [
        {"narration": "a", "visual_type": "slide", "visual_spec": {"title": "A"}, "duration_hint_sec": 3.0},
        {"narration": "b", "visual_type": "slide", "visual_spec": {"title": "B"}, "duration_hint_sec": 3.0}
      ]
    }"""])
    doc = write_script(research_result, llm=llm)
    assert [s.id for s in doc.scenes] == [1, 2]
