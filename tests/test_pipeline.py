from paper2video.pipeline import run_pipeline, PipelineConfig
from paper2video.llm import FakeLLMClient
from paper2video.tts import FakeTTS
from paper2video.ingest import IngestedDoc


def test_run_pipeline_end_to_end(tmp_path, monkeypatch):
    fake_doc = IngestedDoc(
        text="LLMs can build persistent wikis as an alternative to RAG.",
        title="LLM Wikis",
        source_url="https://example.com/a",
    )
    monkeypatch.setattr("paper2video.pipeline.extract_from_url", lambda url: fake_doc)

    llm = FakeLLMClient(responses=[
        '["LLM", "wiki", "RAG"]',
        '{"notes": [], "key_points": ["LLMs can maintain wikis", "RAG has limits"]}',
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
    run_dir = tmp_path / "out" / "test_run"
    assert (run_dir / "ingest.json").exists()
    assert (run_dir / "research.json").exists()
    assert (run_dir / "script.json").exists()
