"""Instagram Reels publisher using the Facebook Graph API."""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

from ..publish import Publisher
from ..types import ContentItem, PlatformPackage, PublishResultRecord
from ._oauth import OAuthTokenStore


_GRAPH_API = "https://graph.facebook.com/v21.0"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class InstagramPublisher(Publisher):
    """Uploads Reels to Instagram via the Facebook Graph API.

    Requires:
    - PAPER2VIDEO_INSTAGRAM_USER_ID env var (your Instagram Business account ID)
    - OAuth tokens from: paper2video --setup-oauth instagram
    """

    def __init__(self, tokens_dir: Path = Path(".tokens")):
        self._token_store = OAuthTokenStore("instagram", tokens_dir)
        self._user_id = os.environ.get("PAPER2VIDEO_INSTAGRAM_USER_ID", "")

    def _get_access_token(self) -> str:
        tokens = self._token_store.load_tokens()
        if tokens is None:
            raise FileNotFoundError("No Instagram tokens. Run: paper2video --setup-oauth instagram")

        if self._token_store.is_expired():
            client_id = os.environ.get("INSTAGRAM_CLIENT_ID", "")
            client_secret = os.environ.get("INSTAGRAM_CLIENT_SECRET", "")
            if not client_id or not client_secret:
                raise RuntimeError("INSTAGRAM_CLIENT_ID and INSTAGRAM_CLIENT_SECRET required for token refresh.")
            tokens = self._token_store.refresh(
                client_id=client_id,
                client_secret=client_secret,
                token_url=f"{_GRAPH_API}/oauth/access_token",
            )
        return tokens["access_token"]

    def publish(self, item: ContentItem, package: PlatformPackage) -> PublishResultRecord:
        if not self._user_id:
            return PublishResultRecord(
                platform="instagram",
                packaging_status="packaged",
                publish_status="failed",
                error="PAPER2VIDEO_INSTAGRAM_USER_ID not set.",
            )

        try:
            import httpx

            access_token = self._get_access_token()

            # Step 1: Create media container for Reels
            # Instagram requires a publicly accessible video URL for server-side fetch.
            # For local files, we use the local file path — this only works if a
            # tunnel (ngrok, etc.) or file server is configured. The video_url field
            # can also accept a pre-uploaded URL.
            video_path = Path(package.video_path)
            caption = f"{package.caption}\n\n{' '.join('#' + h for h in package.hashtags)}"

            container_resp = httpx.post(
                f"{_GRAPH_API}/{self._user_id}/media",
                params={
                    "access_token": access_token,
                    "media_type": "REELS",
                    "video_url": os.environ.get("PAPER2VIDEO_VIDEO_PUBLIC_URL", str(video_path)),
                    "caption": caption,
                    "share_to_feed": "true",
                },
                timeout=30,
            )
            container_resp.raise_for_status()
            creation_id = container_resp.json().get("id", "")

            if not creation_id:
                return PublishResultRecord(
                    platform="instagram",
                    packaging_status="packaged",
                    publish_status="failed",
                    error="No creation_id in container response.",
                )

            # Step 2: Poll container status until FINISHED
            for _ in range(30):
                time.sleep(5)
                status_resp = httpx.get(
                    f"{_GRAPH_API}/{creation_id}",
                    params={
                        "access_token": access_token,
                        "fields": "status_code",
                    },
                    timeout=15,
                )
                status_code = status_resp.json().get("status_code", "")
                if status_code == "FINISHED":
                    break
                if status_code == "ERROR":
                    return PublishResultRecord(
                        platform="instagram",
                        packaging_status="packaged",
                        publish_status="failed",
                        error="Instagram media container processing failed.",
                    )
            else:
                return PublishResultRecord(
                    platform="instagram",
                    packaging_status="packaged",
                    publish_status="failed",
                    error="Timed out waiting for Instagram media processing.",
                )

            # Step 3: Publish the container
            publish_resp = httpx.post(
                f"{_GRAPH_API}/{self._user_id}/media_publish",
                params={
                    "access_token": access_token,
                    "creation_id": creation_id,
                },
                timeout=30,
            )
            publish_resp.raise_for_status()
            media_id = publish_resp.json().get("id", "")

            return PublishResultRecord(
                platform="instagram",
                packaging_status="packaged",
                publish_status="published",
                platform_post_id=media_id,
                platform_url=f"https://www.instagram.com/reel/{media_id}/",
                published_at=_utcnow(),
            )

        except Exception as e:
            return PublishResultRecord(
                platform="instagram",
                packaging_status="packaged",
                publish_status="failed",
                error=str(e),
            )
