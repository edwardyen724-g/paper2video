from paper2video.store import JobStore
from paper2video.types import ContentItem, PublishResultRecord, ReviewActionRecord


def test_job_store_persists_items_reviews_and_publish_results(tmp_path):
    store = JobStore(tmp_path / "workflow.db")
    item = ContentItem(
        source_id="openai_blog:abc",
        title="New model",
        source_type="openai_blog",
        source_priority=100,
        canonical_url="https://openai.com/news/new-model",
    )
    stored = store.upsert_item(item)
    assert stored.source_id == item.source_id

    store.record_review_action(
        ReviewActionRecord(source_id=item.source_id, action_type="revise", reviewer_message="stronger hook")
    )
    store.upsert_publish_result(
        item.source_id,
        PublishResultRecord(
            platform="tiktok",
            packaging_status="packaged",
            publish_status="published",
            platform_post_id="123",
        ),
    )

    fetched = store.get_item(item.source_id)
    assert fetched.source_id == item.source_id
    assert store.list_review_actions(item.source_id)[0].reviewer_message == "stronger hook"
    assert store.list_publish_results(item.source_id)[0].platform_post_id == "123"


def test_job_store_orders_items_by_priority(tmp_path):
    store = JobStore(tmp_path / "workflow.db")
    store.upsert_item(
        ContentItem(
            source_id="low",
            title="low",
            source_type="arxiv",
            source_priority=50,
            canonical_url="https://arxiv.org/abs/1",
            state="queued",
        )
    )
    store.upsert_item(
        ContentItem(
            source_id="high",
            title="high",
            source_type="openai_blog",
            source_priority=100,
            canonical_url="https://openai.com/news/1",
            state="queued",
        )
    )
    queued = store.list_items_by_state("queued")
    assert [item.source_id for item in queued] == ["high", "low"]


def test_job_store_tracks_pending_revision_requests(tmp_path):
    store = JobStore(tmp_path / "workflow.db")
    assert store.get_pending_revision("123") == ""
    store.set_pending_revision("123", "source-a")
    assert store.get_pending_revision("123") == "source-a"
    store.clear_pending_revision("123")
    assert store.get_pending_revision("123") == ""
