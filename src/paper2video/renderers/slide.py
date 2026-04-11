from __future__ import annotations
from pathlib import Path
from ..types import Scene


# 3Blue1Brown-ish palette
BG = "#0f0f1e"
FG = "#f5f5f5"
ACCENT = "#ffc857"


def render_slide(scene: Scene, out_dir: Path, size: tuple[int, int] = (1920, 1080)) -> Path:
    """Render a slide-style scene to a PNG. Pure matplotlib, no LaTeX required.

    Handles both landscape (1920x1080) and portrait (1080x1920) orientations.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    width_px, height_px = size
    is_portrait = height_px > width_px
    dpi = 100
    fig = plt.figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()

    ax.add_patch(Rectangle((0, 0), 1, 1, facecolor=BG, zorder=0))

    spec = scene.visual_spec or {}
    title = str(spec.get("title", ""))
    direction = str(spec.get("direction", ""))
    bullets = [str(b) for b in spec.get("bullets", []) or []]
    caption = str(spec.get("caption", ""))

    if is_portrait:
        # Portrait layout — title near top, larger margins, smaller font for narrow width
        margin_x = 0.10
        ax.add_patch(Rectangle((margin_x, 0.90), 0.06, 0.006, facecolor=ACCENT, zorder=1))

        ax.text(
            margin_x, 0.87, title,
            color=FG, fontsize=36, fontweight="bold",
            ha="left", va="top", wrap=True,
        )

        # Show direction text (the animation description) as the main visual content
        # since the slide is a fallback for failed Manim renders
        body_text = direction if direction else "\n".join(bullets) if bullets else ""
        if body_text:
            ax.text(
                margin_x, 0.75, body_text,
                color=FG, fontsize=22, ha="left", va="top", wrap=True,
                linespacing=1.6,
            )

        # Narration preview at bottom
        narration = scene.narration[:200]
        if narration:
            ax.text(
                0.5, 0.15, narration,
                color="#aaa", fontsize=18, ha="center", va="top", wrap=True,
                style="italic", linespacing=1.4,
            )

        if caption:
            ax.text(
                margin_x, 0.05, caption,
                color=ACCENT, fontsize=18, style="italic", ha="left", va="bottom",
            )
    else:
        # Landscape layout (original)
        ax.add_patch(Rectangle((0.08, 0.82), 0.08, 0.008, facecolor=ACCENT, zorder=1))

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
