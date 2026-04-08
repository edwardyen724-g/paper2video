from paper2video.renderers.manim_r import _strip_code_fences, _compose_visual_direction, lint_manim_code


def test_strip_code_fences_removes_python_fence():
    raw = "```python\nfrom manim import *\nclass MainScene(Scene):\n    pass\n```"
    out = _strip_code_fences(raw)
    assert out.startswith("from manim")
    assert out.endswith("pass")
    assert "```" not in out


def test_strip_code_fences_handles_plain_fence():
    raw = "```\nx = 1\n```"
    assert _strip_code_fences(raw) == "x = 1"


def test_strip_code_fences_leaves_plain_code_alone():
    raw = "from manim import *\nclass MainScene(Scene):\n    pass"
    assert _strip_code_fences(raw) == raw


def test_compose_visual_direction_uses_all_fields():
    spec = {
        "title": "The Flip",
        "direction": "Transform an arrow pointing right into one pointing left",
        "elements": ["box A", "box B", "arrow"],
        "bullets": ["reveal A", "reveal B", "connect"],
        "caption": "this is the key insight",
    }
    out = _compose_visual_direction(spec)
    assert "The Flip" in out
    assert "Transform an arrow" in out
    assert "box A" in out
    assert "reveal A" in out
    assert "this is the key insight" in out


def test_compose_visual_direction_empty_spec():
    assert "invent" in _compose_visual_direction({})


# ---- linter tests ----

GOOD_CODE = """\
from manim import *

class MainScene(Scene):
    def construct(self):
        def fit(mobj, max_w=11.0, max_h=6.0):
            s = min(max_w / mobj.width, max_h / mobj.height, 1.0)
            if s < 1.0:
                mobj.scale(s)
            return mobj

        title = Text("Hello", font_size=44)
        fit(title, max_w=11.0)
        title.to_edge(UP, buff=0.6)
        self.play(Write(title))
        self.wait(1)
"""


def test_lint_passes_on_good_code():
    assert lint_manim_code(GOOD_CODE) == []


def test_lint_catches_scale_to_fit_width():
    code = GOOD_CODE.replace("fit(title, max_w=11.0)", "title.scale_to_fit_width(10)")
    errors = lint_manim_code(code)
    assert any("scale_to_fit_width" in e for e in errors)


def test_lint_catches_scale_to_fit_height():
    code = GOOD_CODE.replace("fit(title, max_w=11.0)", "title.scale_to_fit_height(5)")
    errors = lint_manim_code(code)
    assert any("scale_to_fit" in e for e in errors)


def test_lint_catches_huge_shift():
    bad = GOOD_CODE.replace("self.wait(1)", "title.shift(DOWN * 4)\n        self.wait(1)")
    errors = lint_manim_code(bad)
    assert any("shift" in e for e in errors)


def test_lint_allows_small_shift():
    ok = GOOD_CODE.replace("self.wait(1)", "title.shift(UP * 0.3)\n        self.wait(1)")
    assert lint_manim_code(ok) == []


def test_lint_catches_missing_main_scene():
    code = "from manim import *\n\nclass NotIt(Scene):\n    def construct(self):\n        pass\n"
    errors = lint_manim_code(code)
    assert any("MainScene" in e for e in errors)


def test_lint_catches_forbidden_import():
    code = "from manim import *\nimport numpy as np\n\nclass MainScene(Scene):\n    def construct(self):\n        pass\n"
    errors = lint_manim_code(code)
    assert any("forbidden import" in e for e in errors)


def test_lint_catches_mathtex():
    code = GOOD_CODE.replace("Text(\"Hello\", font_size=44)", "MathTex(r\"x^2\")")
    errors = lint_manim_code(code)
    assert any("LaTeX" in e or "MathTex" in e for e in errors)


def test_lint_catches_fit_call_without_definition():
    bad = """\
from manim import *

class MainScene(Scene):
    def construct(self):
        title = Text("Hi", font_size=44)
        fit(title, 10)
        self.play(Write(title))
"""
    errors = lint_manim_code(bad)
    assert any("def fit" in e for e in errors)
