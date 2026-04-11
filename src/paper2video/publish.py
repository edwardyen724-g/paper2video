from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .types import ContentItem, PlatformPackage, PublishPlatform, PublishResultRecord


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Publisher:
    def publish(self, item: ContentItem, package: PlatformPackage) -> PublishResultRecord:
        raise NotImplementedError


@dataclass
class FakePublisher(Publisher):
    published: list[tuple[str, PlatformPackage]] = field(default_factory=list)

    def publish(self, item: ContentItem, package: PlatformPackage) -> PublishResultRecord:
        self.published.append((item.source_id, package))
        return PublishResultRecord(
            platform=package.platform,
            packaging_status="packaged",
            publish_status="published",
            platform_post_id=f"{package.platform}-{len(self.published)}",
            platform_url=f"https://example.com/{package.platform}/{item.source_id}",
            published_at=_utcnow(),
        )


class CommandPublisher(Publisher):
    """Runs a configured command per platform and treats exit 0 as success."""

    def __init__(self, command_map: dict[PublishPlatform, str]):
        self.command_map = command_map

    def publish(self, item: ContentItem, package: PlatformPackage) -> PublishResultRecord:
        cmd_template = self.command_map.get(package.platform)
        if not cmd_template:
            return PublishResultRecord(
                platform=package.platform,
                packaging_status="packaged",
                publish_status="failed",
                error="No publish command configured.",
            )
        env = os.environ.copy()
        env.update(
            {
                "PAPER2VIDEO_SOURCE_ID": item.source_id,
                "PAPER2VIDEO_TITLE": package.title,
                "PAPER2VIDEO_VIDEO_PATH": package.video_path,
                "PAPER2VIDEO_METADATA_PATH": package.metadata_path,
            }
        )
        proc = subprocess.run(cmd_template, shell=True, text=True, capture_output=True, env=env)
        if proc.returncode != 0:
            return PublishResultRecord(
                platform=package.platform,
                packaging_status="packaged",
                publish_status="failed",
                error=(proc.stderr or proc.stdout).strip(),
            )
        return PublishResultRecord(
            platform=package.platform,
            packaging_status="packaged",
            publish_status="published",
            platform_post_id=(proc.stdout or "").strip(),
            published_at=_utcnow(),
        )


def build_platform_packages(item: ContentItem, master_video_path: Path, out_dir: Path) -> list[PlatformPackage]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base_hashtags = ["AI", "TechExplained", "Research"]
    if item.source_type == "arxiv":
        base_hashtags.append("arXiv")
    else:
        base_hashtags.append("AILabs")
    packages: list[PlatformPackage] = []
    for platform in ("tiktok", "instagram", "xiaohongshu"):
        title = item.title[:80]
        caption = f"{item.summary}\n\nRead more: {item.canonical_url}"
        thumbnail_path = out_dir / f"{platform}_cover.png"
        candidate_thumbnail = master_video_path.parent / "images" / "scene_001.png"
        if candidate_thumbnail.exists():
            thumbnail_path.write_bytes(candidate_thumbnail.read_bytes())
        metadata_path = out_dir / f"{platform}_metadata.json"
        payload = {
            "platform": platform,
            "title": title,
            "caption": caption,
            "hashtags": base_hashtags,
            "source_url": item.canonical_url,
            "thumbnail_path": str(thumbnail_path) if thumbnail_path.exists() else "",
        }
        metadata_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        packages.append(
            PlatformPackage(
                platform=platform,  # type: ignore[arg-type]
                video_path=str(master_video_path),
                caption=caption,
                title=title,
                hashtags=base_hashtags,
                thumbnail_path=str(thumbnail_path) if thumbnail_path.exists() else "",
                metadata_path=str(metadata_path),
            )
        )
    return packages
