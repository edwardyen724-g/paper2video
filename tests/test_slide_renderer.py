from PIL import Image
from paper2video.types import Scene
from paper2video.renderers.slide import render_slide


def test_render_slide_produces_png_at_target_resolution(tmp_path):
    scene = Scene(
        id=1,
        narration="Hello.",
        visual_type="slide",
        visual_spec={"title": "Test Title", "bullets": ["alpha", "beta", "gamma"]},
        duration_hint_sec=4.0,
    )
    out = render_slide(scene, tmp_path, size=(1920, 1080))
    assert out.exists()
    assert out.suffix == ".png"
    with Image.open(out) as img:
        assert img.size == (1920, 1080)


def test_render_slide_handles_missing_bullets(tmp_path):
    scene = Scene(
        id=2, narration="X", visual_type="slide",
        visual_spec={"title": "Only Title"}, duration_hint_sec=3.0,
    )
    out = render_slide(scene, tmp_path)
    assert out.exists()


def test_render_slide_handles_caption(tmp_path):
    scene = Scene(
        id=3, narration="X", visual_type="slide",
        visual_spec={"title": "T", "bullets": ["b"], "caption": "a caption"},
        duration_hint_sec=3.0,
    )
    out = render_slide(scene, tmp_path)
    assert out.exists()
