"""YouTube Shorts publisher using the YouTube Data API v3."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from ..publish import Publisher
from ..types import ContentItem, PlatformPackage, PublishResultRecord
from ._oauth import OAuthTokenStore


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class YouTubePublisher(Publisher):
    """Uploads videos to YouTube Shorts via the Data API v3 with resumable upload."""

    def __init__(self, tokens_dir: Path = Path(".tokens")):
        self._token_store = OAuthTokenStore("youtube", tokens_dir)
        self._service = None

    def _get_service(self):
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        tokens = self._token_store.load_tokens()
        if tokens is None:
            raise FileNotFoundError("No YouTube tokens. Run: paper2video --setup-oauth youtube")

        client_id = os.environ.get("YOUTUBE_CLIENT_ID", "")
        client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "")

        creds = Credentials(
            token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=["https://www.googleapis.com/auth/youtube.upload",
                     "https://www.googleapis.com/auth/youtube.force-ssl"],
        )
        if self._token_store.is_expired() and client_id and client_secret:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            self._token_store.save_tokens(
                access_token=creds.token,
                refresh_token=creds.refresh_token or tokens["refresh_token"],
                expires_at=creds.expiry.timestamp() if creds.expiry else 0,
            )

        self._service = build("youtube", "v3", credentials=creds)
        return self._service

    def publish(self, item: ContentItem, package: PlatformPackage) -> PublishResultRecord:
        try:
            from googleapiclient.http import MediaFileUpload
            from googleapiclient.errors import HttpError

            service = self._get_service()

            body = {
                "snippet": {
                    "title": package.title,
                    "description": package.caption,
                    "tags": package.hashtags,
                    "categoryId": "28",  # Science & Technology
                },
                "status": {
                    "privacyStatus": "public",
                    "selfDeclaredMadeForKids": False,
                },
            }

            media = MediaFileUpload(
                package.video_path,
                mimetype="video/mp4",
                resumable=True,
                chunksize=10 * 1024 * 1024,  # 10MB chunks
            )

            request = service.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )

            response = None
            while response is None:
                _, response = request.next_chunk()

            video_id = response["id"]

            # Upload custom thumbnail if available
            if package.thumbnail_path and Path(package.thumbnail_path).exists():
                try:
                    thumb_media = MediaFileUpload(package.thumbnail_path, mimetype="image/png")
                    service.thumbnails().set(videoId=video_id, media_body=thumb_media).execute()
                except HttpError:
                    pass  # Thumbnail upload is best-effort

            return PublishResultRecord(
                platform="youtube",
                packaging_status="packaged",
                publish_status="published",
                platform_post_id=video_id,
                platform_url=f"https://youtube.com/shorts/{video_id}",
                published_at=_utcnow(),
            )

        except HttpError as e:
            return PublishResultRecord(
                platform="youtube",
                packaging_status="packaged",
                publish_status="failed",
                error=str(e),
            )
        except Exception as e:
            return PublishResultRecord(
                platform="youtube",
                packaging_status="packaged",
                publish_status="failed",
                error=str(e),
            )
