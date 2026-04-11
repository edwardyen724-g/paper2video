from __future__ import annotations

from pathlib import Path

from PIL import Image

from .types import ScriptDoc


def validate_vertical_assets(
    script: ScriptDoc,
    visual_paths: list[Path],
    audio_paths: list[Path],
    captions_path: Path | None,
    expected_size: tuple[int, int] = (1080, 1920),
) -> list[str]:
    errors: list[str] = []
    if captions_path is None or not Path(captions_path).exists():
        errors.append("Missing captions file.")
    if len(visual_paths) != len(script.scenes):
        errors.append("Scene visual count does not match script scenes.")
    if len(audio_paths) != len(script.scenes):
        errors.append("Scene audio count does not match script scenes.")

    for idx, visual_path in enumerate(visual_paths, start=1):
        if not Path(visual_path).exists():
            errors.append(f"Scene {idx} visual is missing.")
            continue
        if visual_path.suffix.lower() == ".png":
            with Image.open(visual_path) as img:
                if img.size != expected_size:
                    errors.append(f"Scene {idx} visual size {img.size} does not match expected {expected_size}.")
    for idx, audio_path in enumerate(audio_paths, start=1):
        if not Path(audio_path).exists() or Path(audio_path).stat().st_size == 0:
            errors.append(f"Scene {idx} audio is missing.")
    return errors
