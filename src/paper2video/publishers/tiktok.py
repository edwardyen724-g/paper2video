"""TikTok publisher using the Content Posting API."""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

from ..publish import Publisher
from ..types import ContentItem, PlatformPackage, PublishResultRecord
from ._oauth import OAuthTokenStore


_API_BASE = "https://open.tiktokapis.com"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class TikTokPublisher(Publisher):
    """Uploads videos to TikTok via the Content Posting API.

    Requires a TikTok developer account with an approved app.
    Set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET in .env.
    """

    def __init__(self, tokens_dir: Path = Path(".tokens")):
        self._token_store = OAuthTokenStore("tiktok", tokens_dir)

    def _get_access_token(self) -> str:
        tokens = self._token_store.load_tokens()
        if tokens is None:
            raise FileNotFoundError("No TikTok tokens. Run: paper2video --setup-oauth tiktok")

        if self._token_store.is_expired():
            client_key = os.environ.get("TIKTOK_CLIENT_KEY", "")
            client_secret = os.environ.get("TIKTOK_CLIENT_SECRET", "")
            if not client_key or not client_secret:
                raise RuntimeError("TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET required for token refresh.")
            tokens = self._token_store.refresh(
                client_id=client_key,
                client_secret=client_secret,
                token_url=f"{_API_BASE}/v2/oauth/token/",
            )
        return tokens["access_token"]

    def publish(self, item: ContentItem, package: PlatformPackage) -> PublishResultRecord:
        try:
            import httpx

            access_token = self._get_access_token()
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }

            video_path = Path(package.video_path)
            video_size = video_path.stat().st_size

            # Step 1: Initialize upload
            init_body = {
                "post_info": {
                    "title": package.title,
                    "privacy_level": "PUBLIC_TO_EVERYONE",
                    "disable_duet": False,
                    "disable_stitch": False,
                    "disable_comment": False,
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": video_size,
                    "chunk_size": video_size,
                    "total_chunk_count": 1,
                },
            }
            resp = httpx.post(
                f"{_API_BASE}/v2/post/publish/inbox/video/init/",
                headers=headers,
                json=init_body,
                timeout=30,
            )
            resp.raise_for_status()
            init_data = resp.json().get("data", {})
            publish_id = init_data.get("publish_id", "")
            upload_url = init_data.get("upload_url", "")

            if not upload_url:
                return PublishResultRecord(
                    platform="tiktok",
                    packaging_status="packaged",
                    publish_status="failed",
                    error="No upload_url in init response.",
                )

            # Step 2: Upload video file
            video_bytes = video_path.read_bytes()
            upload_headers = {
                "Content-Type": "video/mp4",
                "Content-Length": str(video_size),
                "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
            }
            resp = httpx.put(upload_url, content=video_bytes, headers=upload_headers, timeout=120)
            resp.raise_for_status()

            # Step 3: Poll publish status
            for _ in range(20):
                time.sleep(5)
                status_resp = httpx.post(
                    f"{_API_BASE}/v2/post/publish/status/fetch/",
                    headers=headers,
                    json={"publish_id": publish_id},
                    timeout=15,
                )
                status_data = status_resp.json().get("data", {})
                status = status_data.get("status", "")
                if status == "PUBLISH_COMPLETE":
                    return PublishResultRecord(
                        platform="tiktok",
                        packaging_status="packaged",
                        publish_status="published",
                        platform_post_id=publish_id,
                        published_at=_utcnow(),
                    )
                if status in ("FAILED", "PUBLISH_CANCELLED"):
                    return PublishResultRecord(
                        platform="tiktok",
                        packaging_status="packaged",
                        publish_status="failed",
                        error=f"TikTok publish status: {status}",
                    )

            return PublishResultRecord(
                platform="tiktok",
                packaging_status="packaged",
                publish_status="failed",
                error="Timed out waiting for TikTok publish to complete.",
            )

        except Exception as e:
            return PublishResultRecord(
                platform="tiktok",
                packaging_status="packaged",
                publish_status="failed",
                error=str(e),
            )
