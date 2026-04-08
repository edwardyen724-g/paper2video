from __future__ import annotations
from pathlib import Path
from ..types import Scene


# 3Blue1Brown-ish palette
BG = "#0f0f1e"
FG = "#f5f5f5"
ACCENT = "#ffc857"


def render_slide(scene: Scene, out_dir: Path, size: tuple[int, int] = (1920, 1080)) -> Path:
    """Render a slide-style scene to a PNG. Pure matplotlib, no LaTeX required."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    width_px, height_px = size
    dpi = 100
    fig = plt.figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()

    ax.add_patch(Rectangle((0, 0), 1, 1, facecolor=BG, zorder=0))
    ax.add_patch(Rectangle((0.08, 0.82), 0.08, 0.008, facecolor=ACCENT, zorder=1))

    spec = scene.visual_spec or {}
    title = str(spec.get("title", ""))
    bullets = [str(b) for b in spec.get("bullets", []) or []]
    caption = str(spec.get("caption", ""))

    ax.text(
        0.08, 0.78, title,
        color=FG, fontsize=52, fontweight="bold",
        ha="left", va="top", wrap=True,
    )

    for i, b in enumerate(bullets[:6]):
        ax.text(
            0.10, 0.62 - i * 0.09, f"\u2022  {b}",
            color=FG, fontsize=32, ha="left", va="top", wrap=True,
        )

    if caption:
        ax.text(
            0.08, 0.08, caption,
            color=ACCENT, fontsize=24, style="italic", ha="left", va="bottom",
        )

    ax.text(
        0.98, 0.04, f"{scene.id:02d}",
        color="#888", fontsize=18, ha="right", va="bottom",
    )

    out_path = out_dir / f"scene_{scene.id:03d}.png"
    fig.savefig(out_path, dpi=dpi, facecolor=BG)
    plt.close(fig)
    return out_path
