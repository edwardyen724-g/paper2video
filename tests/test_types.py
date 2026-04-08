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
