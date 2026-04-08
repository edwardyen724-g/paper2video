from __future__ import annotations
from pathlib import Path
from typing import Protocol
from ..types import Scene


class Renderer(Protocol):
    def render(self, scene: Scene, out_dir: Path) -> Path:
        """Render a scene to a file and return the path."""
        ...
