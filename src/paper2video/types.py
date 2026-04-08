from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field

VisualType = Literal["slide", "manim", "image"]


class Source(BaseModel):
    url: str
    title: str = ""


class ResearchNote(BaseModel):
    claim: str
    sources: list[Source] = Field(default_factory=list)


class Scene(BaseModel):
    id: int
    narration: str
    visual_type: VisualType = "slide"
    visual_spec: dict = Field(default_factory=dict)
    duration_hint_sec: float = 5.0


class ScriptDoc(BaseModel):
    title: str
    summary: str
    scenes: list[Scene]
