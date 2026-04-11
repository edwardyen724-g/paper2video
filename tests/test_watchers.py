from paper2video.store import JobStore
from paper2video.watchers import WatchSource, discover_content, queue_discovered_content


def test_discover_content_detects_lab_posts_and_arxiv_and_orders_by_priority():
    openai_html = """
    <html><body>
      <a href="/news/new-model/">OpenAI launches a new model</a>
      <a href="/news/new-model/">Duplicate link</a>
    </body></html>
    """
    arxiv_atom = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>http://arxiv.org/abs/1234.5678v1</id>
        <title>Fast agents for vision-language reasoning</title>
        <published>2026-04-10T00:00:00Z</published>
      </entry>
    </feed>
    """
    sources = [
        WatchSource("OpenAI", "openai_blog", "https://openai.com/news/", 100, "html"),
        WatchSource("arXiv", "arxiv", "https://export.arxiv.org/api/query?x", 50, "atom"),
    ]

    def fake_fetch(url: str) -> str:
        if "openai.com" in url:
            return openai_html
        return arxiv_atom

    items = discover_content(sources=sources, fetch_text=fake_fetch)
    assert len(items) == 2
    assert items[0].source_type == "openai_blog"
    assert items[1].source_type == "arxiv"
    assert items[0].canonical_url == "https://openai.com/news/new-model/"


def test_queue_discovered_content_deduplicates_existing_items(tmp_path):
    html = '<a href="/news/new-model/">OpenAI launches a new model</a>'
    store = JobStore(tmp_path / "workflow.db")
    sources = [WatchSource("OpenAI", "openai_blog", "https://openai.com/news/", 100, "html")]

    queued_first = queue_discovered_content(store, sources=sources, fetch_text=lambda _: html)
    queued_second = queue_discovered_content(store, sources=sources, fetch_text=lambda _: html)

    assert len(queued_first) == 1
    assert queued_second == []
