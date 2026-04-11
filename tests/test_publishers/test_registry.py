from paper2video.publish import FakePublisher, PublisherRegistry
from paper2video.types import ContentItem, PlatformPackage


def _item() -> ContentItem:
    return ContentItem(
        source_id="test:1",
        title="Test",
        source_type="arxiv",
        source_priority=50,
        canonical_url="https://example.com",
    )


def _package(platform: str) -> PlatformPackage:
    return PlatformPackage(
        platform=platform,  # type: ignore[arg-type]
        video_path="/fake.mp4",
        caption="test",
        title="Test",
    )


def test_registry_routes_to_registered_publisher():
    yt_pub = FakePublisher()
    registry = PublisherRegistry()
    registry.register("youtube", yt_pub)
    assert registry.get("youtube") is yt_pub


def test_registry_falls_back_to_default():
    default = FakePublisher()
    registry = PublisherRegistry(default=default)
    assert registry.get("tiktok") is default


def test_registry_returns_none_when_no_default():
    registry = PublisherRegistry()
    assert registry.get("instagram") is None


def test_registry_registered_overrides_default():
    default = FakePublisher()
    specific = FakePublisher()
    registry = PublisherRegistry(default=default)
    registry.register("youtube", specific)
    assert registry.get("youtube") is specific
    assert registry.get("tiktok") is default


def test_publish_through_registry():
    pub = FakePublisher()
    registry = PublisherRegistry()
    registry.register("youtube", pub)
    item = _item()
    pkg = _package("youtube")
    result = registry.get("youtube").publish(item, pkg)
    assert result.publish_status == "published"
    assert len(pub.published) == 1
