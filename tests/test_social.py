from pathlib import Path

from paper2video.ingest import IngestedDoc
from paper2video.llm import FakeLLMClient
from paper2video.publish import FakePublisher
from paper2video.review import FakeTelegramReviewClient
from paper2video.social import (
    SocialWorkflowDependencies,
    approve_and_publish,
    generate_social_draft,
    process_telegram_updates,
    revise_social_draft,
    skip_item,
)
from paper2video.store import JobStore
from paper2video.tts import FakeTTS
from paper2video.types import ContentItem, SocialGenerationConfig


def _script_response(title: str = "Fast Wiki Pattern", first_line: str = "This paper changes how agents remember things."):
    return f"""{{
      "title": "{title}",
      "summary": "A fast explanation of the main idea.",
      "scenes": [
        {{"id": 1, "narration": "{first_line}", "visual_type": "slide",
          "visual_spec": {{"title": "Hook", "bullets": ["better memory", "faster answers"]}}, "duration_hint_sec": 8.0}},
        {{"id": 2, "narration": "Instead of searching from scratch, it keeps a growing knowledge base.", "visual_type": "slide",
          "visual_spec": {{"title": "Core idea", "bullets": ["persistent wiki"]}}, "duration_hint_sec": 8.0}},
        {{"id": 3, "narration": "That means each new document compounds on the last one.", "visual_type": "slide",
          "visual_spec": {{"title": "Compounding", "bullets": ["knowledge compounds"]}}, "duration_hint_sec": 8.0}},
        {{"id": 4, "narration": "It matters because the system gets more useful over time.", "visual_type": "slide",
          "visual_spec": {{"title": "Why it matters", "bullets": ["long-term memory"]}}, "duration_hint_sec": 8.0}}
      ]
    }}"""


def test_social_draft_review_revision_and_publish_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "paper2video.social.extract_from_url",
        lambda url: IngestedDoc(
            text="LLMs can keep a persistent wiki instead of doing retrieval from scratch each time.",
            title="Persistent wiki agents",
            source_url=url,
        ),
    )

    llm = FakeLLMClient(
        responses=[
            '["persistent memory", "wiki", "retrieval"]',
            '{"notes": [], "key_points": ["hook", "idea", "why it matters"]}',
            _script_response(),
            """{
              "title": "Sharper Hook",
              "summary": "A tighter cut with a better hook.",
              "changed_scene_ids": [1],
              "scenes": [
                {"id": 1, "narration": "Most AI videos explain one paper. This one shows how an AI can keep getting smarter.", "visual_type": "slide",
                 "visual_spec": {"title": "Sharper hook", "bullets": ["keeps getting smarter"]}, "duration_hint_sec": 8.0},
                {"id": 2, "narration": "Instead of searching from scratch, it keeps a growing knowledge base.", "visual_type": "slide",
                 "visual_spec": {"title": "Core idea", "bullets": ["persistent wiki"]}, "duration_hint_sec": 8.0},
                {"id": 3, "narration": "That means each new document compounds on the last one.", "visual_type": "slide",
                 "visual_spec": {"title": "Compounding", "bullets": ["knowledge compounds"]}, "duration_hint_sec": 8.0},
                {"id": 4, "narration": "It matters because the system gets more useful over time.", "visual_type": "slide",
                 "visual_spec": {"title": "Why it matters", "bullets": ["long-term memory"]}, "duration_hint_sec": 8.0}
              ]
            }""",
        ]
    )
    store = JobStore(tmp_path / "workflow.db")
    reviewer = FakeTelegramReviewClient()
    publisher = FakePublisher()
    deps = SocialWorkflowDependencies(
        llm=llm,
        tts=FakeTTS(),
        store=store,
        review_client=reviewer,
        publisher=publisher,
    )
    item = ContentItem(
        source_id="openai_blog:abc",
        title="Persistent wiki agents",
        source_type="openai_blog",
        source_priority=100,
        canonical_url="https://example.com/post",
        state="queued",
    )
    cfg = SocialGenerationConfig(out_dir=str(tmp_path / "out"), use_manim=False)

    draft = generate_social_draft(item, cfg=cfg, deps=deps)
    assert Path(draft.review_video_path).exists()
    assert Path(draft.captions_path).exists()
    assert store.get_item(item.source_id).state == "awaiting_review"
    assert len(reviewer.sent_drafts) == 1

    revised = revise_social_draft(item.source_id, "make the intro punchier", cfg=cfg, deps=deps)
    assert revised.item.revision_count == 1
    assert store.get_item(item.source_id).state == "awaiting_review"
    assert len(reviewer.sent_drafts) == 2

    results = approve_and_publish(item.source_id, deps=deps)
    assert {result.platform for result in results} == {"tiktok", "instagram", "xiaohongshu", "youtube"}
    assert store.get_item(item.source_id).state == "published"
    assert len(publisher.published) == 4


def test_skip_item_marks_content_as_skipped(tmp_path):
    store = JobStore(tmp_path / "workflow.db")
    item = ContentItem(
        source_id="arxiv:1",
        title="A paper",
        source_type="arxiv",
        source_priority=50,
        canonical_url="https://arxiv.org/abs/1",
        state="awaiting_review",
    )
    store.upsert_item(item)
    skipped = skip_item(
        item.source_id,
        deps=SocialWorkflowDependencies(
            llm=FakeLLMClient(responses=[]),
            tts=FakeTTS(),
            store=store,
            review_client=FakeTelegramReviewClient(),
            publisher=FakePublisher(),
        ),
        reviewer_message="not strong enough",
    )
    assert skipped.state == "skipped"


def test_process_telegram_updates_handles_revise_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "paper2video.social.extract_from_url",
        lambda url: IngestedDoc(
            text="LLMs can keep a persistent wiki instead of doing retrieval from scratch each time.",
            title="Persistent wiki agents",
            source_url=url,
        ),
    )

    class FakePollingTelegram(FakeTelegramReviewClient):
        def __init__(self, updates):
            super().__init__()
            self.updates = updates
            self.answered = []
            self.messages = []

        def get_updates(self, offset=None, timeout=0):
            return self.updates

        def answer_callback_query(self, callback_query_id: str, text: str = ""):
            self.answered.append((callback_query_id, text))

        def send_text(self, text: str, chat_id: str | None = None) -> str:
            self.messages.append((chat_id, text))
            return "1"

    llm = FakeLLMClient(
        responses=[
            '["persistent memory", "wiki", "retrieval"]',
            '{"notes": [], "key_points": ["hook", "idea", "why it matters"]}',
            _script_response(),
            """{
              "title": "Sharper Hook",
              "summary": "A tighter cut with a better hook.",
              "changed_scene_ids": [1],
              "scenes": [
                {"id": 1, "narration": "Most AI videos explain one paper. This one shows how an AI can keep getting smarter.", "visual_type": "slide",
                 "visual_spec": {"title": "Sharper hook", "bullets": ["keeps getting smarter"]}, "duration_hint_sec": 8.0},
                {"id": 2, "narration": "Instead of searching from scratch, it keeps a growing knowledge base.", "visual_type": "slide",
                 "visual_spec": {"title": "Core idea", "bullets": ["persistent wiki"]}, "duration_hint_sec": 8.0},
                {"id": 3, "narration": "That means each new document compounds on the last one.", "visual_type": "slide",
                 "visual_spec": {"title": "Compounding", "bullets": ["knowledge compounds"]}, "duration_hint_sec": 8.0},
                {"id": 4, "narration": "It matters because the system gets more useful over time.", "visual_type": "slide",
                 "visual_spec": {"title": "Why it matters", "bullets": ["long-term memory"]}, "duration_hint_sec": 8.0}
              ]
            }""",
        ]
    )
    updates = [
        {
            "update_id": 1,
            "callback_query": {
                "id": "cb-1",
                "data": "revise:openai_blog:abc",
                "message": {"chat": {"id": 2030711424}},
            },
        },
        {
            "update_id": 2,
            "message": {"chat": {"id": 2030711424}, "text": "make the hook punchier"},
        },
    ]
    reviewer = FakePollingTelegram(updates)
    store = JobStore(tmp_path / "workflow.db")
    publisher = FakePublisher()
    deps = SocialWorkflowDependencies(
        llm=llm,
        tts=FakeTTS(),
        store=store,
        review_client=reviewer,
        publisher=publisher,
    )
    item = ContentItem(
        source_id="openai_blog:abc",
        title="Persistent wiki agents",
        source_type="openai_blog",
        source_priority=100,
        canonical_url="https://example.com/post",
        state="queued",
    )
    cfg = SocialGenerationConfig(out_dir=str(tmp_path / "out"), use_manim=False)
    generate_social_draft(item, cfg=cfg, deps=deps)

    processed = process_telegram_updates(cfg=cfg, deps=deps)
    assert processed == 2
    assert reviewer.answered[0][0] == "cb-1"
    assert store.get_item(item.source_id).revision_count == 1
    assert len(reviewer.sent_drafts) == 2
