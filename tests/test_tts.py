import wave
from paper2video.tts import FakeTTS, synthesize_scene_audio
from paper2video.types import Scene


def test_fake_tts_writes_wav(tmp_path):
    engine = FakeTTS(sample_rate=22050)
    out = engine.synthesize("hello world", tmp_path / "a.wav")
    assert out.exists()
    with wave.open(str(out)) as w:
        assert w.getframerate() == 22050
        assert w.getnframes() > 0


def test_synthesize_scene_audio_returns_path_and_duration(tmp_path):
    engine = FakeTTS()
    scene = Scene(id=1, narration="hi there", visual_type="slide",
                  visual_spec={"title": "t"}, duration_hint_sec=3.0)
    result = synthesize_scene_audio(scene, engine, tmp_path)
    assert result.audio_path.exists()
    assert result.duration_sec > 0


def test_fake_tts_duration_proportional_to_text(tmp_path):
    engine = FakeTTS()
    short = engine.synthesize("hi", tmp_path / "short.wav")
    long = engine.synthesize("this is a much longer sentence with many words", tmp_path / "long.wav")
    with wave.open(str(short)) as s, wave.open(str(long)) as l:
        assert l.getnframes() > s.getnframes()
