import subprocess
from pathlib import Path
from paper2video.assemble import build_concat_list, assemble_video, _ffmpeg, _ffprobe_duration
from paper2video.tts import FakeTTS, synthesize_scene_audio
from paper2video.renderers.slide import render_slide
from paper2video.types import Scene


def test_build_concat_list_format(tmp_path):
    lines = build_concat_list([tmp_path / "a.mp4", tmp_path / "b.mp4"])
    assert "file '" in lines
    assert "a.mp4" in lines
    assert "b.mp4" in lines


def test_assemble_video_produces_mp4(tmp_path):
    scenes = [
        Scene(id=1, narration="first scene", visual_type="slide",
              visual_spec={"title": "One", "bullets": ["a"]}, duration_hint_sec=3.0),
        Scene(id=2, narration="second scene", visual_type="slide",
              visual_spec={"title": "Two", "bullets": ["b"]}, duration_hint_sec=3.0),
    ]
    img_dir = tmp_path / "img"
    images = [render_slide(s, img_dir) for s in scenes]
    audio_dir = tmp_path / "audio"
    engine = FakeTTS()
    audios = [synthesize_scene_audio(s, engine, audio_dir) for s in scenes]
    durations = [a.duration_sec for a in audios]

    out = assemble_video(
        images=images,
        audio_paths=[a.audio_path for a in audios],
        durations=durations,
        out_path=tmp_path / "final.mp4",
        work_dir=tmp_path / "work",
    )
    assert out.exists()
    assert out.stat().st_size > 0
    total = _ffprobe_duration(out)
    if total is not None:
        assert total > sum(durations) - 0.5
