from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field

VisualType = Literal["slide", "manim", "image"]
ContentState = Literal[
    "detected",
    "queued",
    "draft_generating",
    "awaiting_review",
    "revision_requested",
    "approved",
    "publishing",
    "published",
    "skipped",
    "failed",
]
ReviewActionType = Literal["approve", "revise", "skip"]
PublishPlatform = Literal["tiktok", "instagram", "xiaohongshu"]
PublishStatus = Literal["pending", "packaged", "published", "failed"]
SourceType = Literal["openai_blog", "anthropic_blog", "deepmind_blog", "meta_ai_blog", "arxiv"]


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


class SocialGenerationConfig(BaseModel):
    mode: Literal["social_review"] = "social_review"
    width: int = 1080
    height: int = 1920
    target_duration_sec: tuple[int, int] = (45, 60)
    captions_enabled: bool = True
    use_manim: bool = True
    out_dir: str = "out/social"
    enable_search: bool = True
    fps: int = 30


class PublishResultRecord(BaseModel):
    platform: PublishPlatform
    packaging_status: str = "pending"
    publish_status: PublishStatus = "pending"
    platform_post_id: str = ""
    platform_url: str = ""
    published_at: str = ""
    error: str = ""


class ContentItem(BaseModel):
    source_id: str
    title: str
    source_type: SourceType
    source_priority: int
    canonical_url: str
    state: ContentState = "detected"
    revision_count: int = 0
    approved_master_asset_path: str = ""
    latest_run_dir: str = ""
    summary: str = ""
    source_published_at: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_metadata: dict = Field(default_factory=dict)
    publish_results: list[PublishResultRecord] = Field(default_factory=list)


class ReviewActionRecord(BaseModel):
    source_id: str
    action_type: ReviewActionType
    reviewer_message: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SocialDraft(BaseModel):
    item: ContentItem
    script: ScriptDoc
    run_dir: str
    master_video_path: str
    review_video_path: str
    captions_path: str = ""
    validation_errors: list[str] = Field(default_factory=list)


class PlatformPackage(BaseModel):
    platform: PublishPlatform
    video_path: str
    caption: str
    title: str
    hashtags: list[str] = Field(default_factory=list)
    thumbnail_path: str = ""
    metadata_path: str = ""
