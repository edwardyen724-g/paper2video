from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .types import ContentItem, PublishResultRecord, ReviewActionRecord


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    """Durable SQLite store for the social review and publish workflow."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS content_items (
                    source_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_priority INTEGER NOT NULL,
                    canonical_url TEXT NOT NULL,
                    state TEXT NOT NULL,
                    revision_count INTEGER NOT NULL,
                    approved_master_asset_path TEXT NOT NULL,
                    latest_run_dir TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    source_published_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    source_metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    reviewer_message TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS publish_results (
                    source_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    packaging_status TEXT NOT NULL,
                    publish_status TEXT NOT NULL,
                    platform_post_id TEXT NOT NULL,
                    platform_url TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    error TEXT NOT NULL,
                    PRIMARY KEY (source_id, platform)
                );
                CREATE TABLE IF NOT EXISTS workflow_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pending_revision_requests (
                    chat_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def upsert_item(self, item: ContentItem) -> ContentItem:
        payload = item.model_copy(update={"updated_at": _utcnow()})
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO content_items (
                    source_id, title, source_type, source_priority, canonical_url, state,
                    revision_count, approved_master_asset_path, latest_run_dir, summary,
                    source_published_at, created_at, updated_at, source_metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    title=excluded.title,
                    source_type=excluded.source_type,
                    source_priority=excluded.source_priority,
                    canonical_url=excluded.canonical_url,
                    state=excluded.state,
                    revision_count=excluded.revision_count,
                    approved_master_asset_path=excluded.approved_master_asset_path,
                    latest_run_dir=excluded.latest_run_dir,
                    summary=excluded.summary,
                    source_published_at=excluded.source_published_at,
                    updated_at=excluded.updated_at,
                    source_metadata_json=excluded.source_metadata_json
                """,
                (
                    payload.source_id,
                    payload.title,
                    payload.source_type,
                    payload.source_priority,
                    payload.canonical_url,
                    payload.state,
                    payload.revision_count,
                    payload.approved_master_asset_path,
                    payload.latest_run_dir,
                    payload.summary,
                    payload.source_published_at,
                    payload.created_at,
                    payload.updated_at,
                    json.dumps(payload.source_metadata, ensure_ascii=False),
                ),
            )
        return self.get_item(payload.source_id)

    def get_item(self, source_id: str) -> ContentItem:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM content_items WHERE source_id = ?", (source_id,)
            ).fetchone()
        if row is None:
            raise KeyError(source_id)
        item = ContentItem(
            source_id=row["source_id"],
            title=row["title"],
            source_type=row["source_type"],
            source_priority=row["source_priority"],
            canonical_url=row["canonical_url"],
            state=row["state"],
            revision_count=row["revision_count"],
            approved_master_asset_path=row["approved_master_asset_path"],
            latest_run_dir=row["latest_run_dir"],
            summary=row["summary"],
            source_published_at=row["source_published_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            source_metadata=json.loads(row["source_metadata_json"]),
            publish_results=self.list_publish_results(row["source_id"]),
        )
        return item

    def list_items_by_state(self, *states: str) -> list[ContentItem]:
        if not states:
            query = "SELECT source_id FROM content_items ORDER BY source_priority DESC, created_at ASC"
            params: tuple[object, ...] = ()
        else:
            placeholders = ",".join("?" for _ in states)
            query = (
                f"SELECT source_id FROM content_items WHERE state IN ({placeholders}) "
                "ORDER BY source_priority DESC, created_at ASC"
            )
            params = tuple(states)
        with self._connect() as conn:
            ids = [row["source_id"] for row in conn.execute(query, params).fetchall()]
        return [self.get_item(source_id) for source_id in ids]

    def record_review_action(self, action: ReviewActionRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO review_actions (source_id, action_type, reviewer_message, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (action.source_id, action.action_type, action.reviewer_message, action.timestamp),
            )

    def list_review_actions(self, source_id: str) -> list[ReviewActionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT source_id, action_type, reviewer_message, timestamp
                FROM review_actions
                WHERE source_id = ?
                ORDER BY id ASC
                """,
                (source_id,),
            ).fetchall()
        return [ReviewActionRecord(**dict(row)) for row in rows]

    def upsert_publish_result(self, source_id: str, result: PublishResultRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO publish_results (
                    source_id, platform, packaging_status, publish_status,
                    platform_post_id, platform_url, published_at, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, platform) DO UPDATE SET
                    packaging_status=excluded.packaging_status,
                    publish_status=excluded.publish_status,
                    platform_post_id=excluded.platform_post_id,
                    platform_url=excluded.platform_url,
                    published_at=excluded.published_at,
                    error=excluded.error
                """,
                (
                    source_id,
                    result.platform,
                    result.packaging_status,
                    result.publish_status,
                    result.platform_post_id,
                    result.platform_url,
                    result.published_at,
                    result.error,
                ),
            )

    def list_publish_results(self, source_id: str) -> list[PublishResultRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT platform, packaging_status, publish_status, platform_post_id,
                       platform_url, published_at, error
                FROM publish_results
                WHERE source_id = ?
                ORDER BY platform ASC
                """,
                (source_id,),
            ).fetchall()
        return [PublishResultRecord(**dict(row)) for row in rows]

    def update_item_state(self, source_id: str, state: str) -> ContentItem:
        item = self.get_item(source_id)
        item.state = state
        return self.upsert_item(item)

    def increment_revision_count(self, source_id: str) -> ContentItem:
        item = self.get_item(source_id)
        item.revision_count += 1
        return self.upsert_item(item)

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_meta (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )

    def get_meta(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM workflow_meta WHERE key = ?", (key,)).fetchone()
        return default if row is None else str(row["value"])

    def set_pending_revision(self, chat_id: str, source_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_revision_requests (chat_id, source_id, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    source_id=excluded.source_id,
                    created_at=excluded.created_at
                """,
                (chat_id, source_id, _utcnow()),
            )

    def get_pending_revision(self, chat_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT source_id FROM pending_revision_requests WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        return "" if row is None else str(row["source_id"])

    def clear_pending_revision(self, chat_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM pending_revision_requests WHERE chat_id = ?", (chat_id,))
