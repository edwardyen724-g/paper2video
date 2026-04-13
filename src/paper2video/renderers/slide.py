from __future__ import annotations
import hashlib
from pathlib import Path
from ..types import Scene


# ---------- Theme system ----------
# Each theme defines a distinct visual identity so videos don't look cookie-cutter.

_THEMES = [
    # 0: 3Blue1Brown classic
    {"bg": "#0f0f1e", "fg": "#f5f5f5", "accent": "#ffc857", "accent2": "#58a6ff", "style": "bar"},
    # 1: Deep ocean
    {"bg": "#0a192f", "fg": "#e6f1ff", "accent": "#64ffda", "accent2": "#f78166", "style": "dot"},
    # 2: Warm slate
    {"bg": "#1a1a2e", "fg": "#eaeaea", "accent": "#e94560", "accent2": "#0f3460", "style": "line"},
    # 3: Forest
    {"bg": "#1b2d1b", "fg": "#e8f5e8", "accent": "#a8e6a3", "accent2": "#ffd93d", "style": "bar"},
    # 4: Sunset
    {"bg": "#2d1b2e", "fg": "#fce4ec", "accent": "#ff6b6b", "accent2": "#feca57", "style": "dot"},
    # 5: Arctic
    {"bg": "#0d1b2a", "fg": "#e0e1dd", "accent": "#48cae4", "accent2": "#90e0ef", "style": "line"},
    # 6: Ember
    {"bg": "#1c1c1c", "fg": "#f0e6d3", "accent": "#ff9f1c", "accent2": "#e71d36", "style": "bar"},
    # 7: Lavender
    {"bg": "#1a1333", "fg": "#f0e6ff", "accent": "#c084fc", "accent2": "#67e8f9", "style": "dot"},
    # 8: Mint
    {"bg": "#0f2027", "fg": "#e0f7f0", "accent": "#2ee09a", "accent2": "#11998e", "style": "line"},
    # 9: Copper
    {"bg": "#1c1410", "fg": "#f5e6d3", "accent": "#d4a373", "accent2": "#e9c46a", "style": "bar"},
]


def _pick_theme(seed: str | None) -> dict:
    """Deterministically pick a theme from a seed string (e.g. source_id)."""
    if seed is None:
        return _THEMES[0]
    idx = int(hashlib.sha1(seed.encode()).hexdigest(), 16) % len(_THEMES)
    return _THEMES[idx]


def _draw_accent_mark(ax, x: float, y: float, style: str, color: str, is_portrait: bool):
    """Draw a small decorative accent mark. Style varies per theme."""
    from matplotlib.patches import Rectangle, Circle

    if style == "bar":
        w = 0.06 if not is_portrait else 0.06
        h = 0.008 if not is_portrait else 0.006
        ax.add_patch(Rectangle((x, y), w, h, facecolor=color, zorder=1))
    elif style == "dot":
        r = 0.008 if not is_portrait else 0.006
        for i in range(3):
            ax.add_patch(Circle((x + i * 0.025, y + 0.003), r, facecolor=color, zorder=1))
    elif style == "line":
        ax.plot([x, x + 0.12], [y, y], color=color, linewidth=2.5, zorder=1)


def render_slide(
    scene: Scene,
    out_dir: Path,
    size: tuple[int, int] = (1920, 1080),
    theme_seed: str | None = None,
) -> Path:
    """Render a slide-style scene to a PNG. Pure matplotlib, no LaTeX required.

    Handles both landscape (1920x1080) and portrait (1080x1920) orientations.
    Uses theme_seed to deterministically vary colors and layout accents per video.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    theme = _pick_theme(theme_seed)
    bg = theme["bg"]
    fg = theme["fg"]
    accent = theme["accent"]
    accent2 = theme["accent2"]
    style = theme["style"]

    width_px, height_px = size
    is_portrait = height_px > width_px
    dpi = 100
    fig = plt.figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()

    ax.add_patch(Rectangle((0, 0), 1, 1, facecolor=bg, zorder=0))

    spec = scene.visual_spec or {}
    title = str(spec.get("title", ""))
    direction = str(spec.get("direction", ""))
    bullets = [str(b) for b in spec.get("bullets", []) or []]
    caption = str(spec.get("caption", ""))

    if is_portrait:
        margin_x = 0.10
        _draw_accent_mark(ax, margin_x, 0.90, style, accent, is_portrait)

        ax.text(
            margin_x, 0.87, title,
            color=fg, fontsize=36, fontweight="bold",
            ha="left", va="top", wrap=True,
        )

        body_text = direction if direction else "\n".join(bullets) if bullets else ""
        if body_text:
            ax.text(
                margin_x, 0.75, body_text,
                color=fg, fontsize=22, ha="left", va="top", wrap=True,
                linespacing=1.6,
            )

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
                color=accent, fontsize=18, style="italic", ha="left", va="bottom",
            )
    else:
        _draw_accent_mark(ax, 0.08, 0.82, style, accent, is_portrait)

        ax.text(
            0.08, 0.78, title,
            color=fg, fontsize=52, fontweight="bold",
            ha="left", va="top", wrap=True,
        )

        # Alternate bullet color between accent and accent2
        for i, b in enumerate(bullets[:6]):
            bullet_color = accent2 if i % 2 == 1 else fg
            ax.text(
                0.10, 0.62 - i * 0.09, f"\u2022  {b}",
                color=bullet_color, fontsize=32, ha="left", va="top", wrap=True,
            )

        if caption:
            ax.text(
                0.08, 0.08, caption,
                color=accent, fontsize=24, style="italic", ha="left", va="bottom",
            )

    ax.text(
        0.98, 0.04, f"{scene.id:02d}",
        color="#888", fontsize=18, ha="right", va="bottom",
    )

    out_path = out_dir / f"scene_{scene.id:03d}.png"
    fig.savefig(out_path, dpi=dpi, facecolor=bg)
    plt.close(fig)
    return out_path
