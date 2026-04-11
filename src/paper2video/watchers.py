from __future__ import annotations

import hashlib
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser

from .store import JobStore
from .types import ContentItem, SourceType


@dataclass(frozen=True)
class WatchSource:
    name: str
    source_type: SourceType
    url: str
    priority: int
    kind: str = "html"


def default_watch_sources() -> list[WatchSource]:
    return [
        WatchSource("OpenAI", "openai_blog", "https://openai.com/news/", 100, "html"),
        WatchSource("Anthropic", "anthropic_blog", "https://www.anthropic.com/news", 95, "html"),
        WatchSource("Google DeepMind", "deepmind_blog", "https://deepmind.google/discover/blog/", 90, "html"),
        WatchSource("Meta AI", "meta_ai_blog", "https://ai.meta.com/blog/", 85, "html"),
        WatchSource(
            "arXiv",
            "arxiv",
            "https://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.CL+OR+cat:cs.LG+OR+cat:cs.CV&sortBy=submittedDate&sortOrder=descending&max_results=20",
            50,
            "atom",
        ),
    ]


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[tuple[str, str]] = []
        self._href = ""
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_dict = dict(attrs)
        self._href = attrs_dict.get("href") or ""
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href:
            return
        text = re.sub(r"\s+", " ", "".join(self._parts)).strip()
        if text:
            self.items.append((self._href, text))
        self._href = ""
        self._parts = []


def _fetch_text(url: str, timeout: float = 20.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "paper2video-social/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _canonicalize(base_url: str, href: str) -> str:
    return urllib.parse.urljoin(base_url, href.split("#", 1)[0])


def _source_id(source_type: SourceType, canonical_url: str) -> str:
    digest = hashlib.sha1(canonical_url.encode("utf-8")).hexdigest()[:12]
    return f"{source_type}:{digest}"


def _looks_like_article(url: str, text: str) -> bool:
    lower_url = url.lower()
    lower_text = text.lower()
    if len(text.strip()) < 12:
        return False
    patterns = ("/news/", "/blog/", "/research/", "/index/", "/posts/")
    return any(pattern in lower_url for pattern in patterns) or "paper" in lower_text or "model" in lower_text


def _parse_html_listing(source: WatchSource, html: str) -> list[ContentItem]:
    parser = _AnchorParser()
    parser.feed(html)
    seen_urls: set[str] = set()
    items: list[ContentItem] = []
    for href, text in parser.items:
        url = _canonicalize(source.url, href)
        if urllib.parse.urlparse(url).netloc != urllib.parse.urlparse(source.url).netloc:
            continue
        if url in seen_urls or not _looks_like_article(url, text):
            continue
        seen_urls.add(url)
        items.append(
            ContentItem(
                source_id=_source_id(source.source_type, url),
                title=text,
                source_type=source.source_type,
                source_priority=source.priority,
                canonical_url=url,
                state="detected",
                source_metadata={"watch_source": source.name},
            )
        )
    return items


def _text_or_empty(node: ET.Element | None, tag: str) -> str:
    if node is None:
        return ""
    found = node.find(tag)
    return (found.text or "").strip() if found is not None else ""


def _parse_atom_listing(source: WatchSource, xml_text: str) -> list[ContentItem]:
    root = ET.fromstring(xml_text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    items: list[ContentItem] = []
    for entry in root.findall("a:entry", ns):
        entry_id = _text_or_empty(entry, "{http://www.w3.org/2005/Atom}id")
        title = _text_or_empty(entry, "{http://www.w3.org/2005/Atom}title")
        published = _text_or_empty(entry, "{http://www.w3.org/2005/Atom}published")
        if not entry_id or not title:
            continue
        items.append(
            ContentItem(
                source_id=_source_id(source.source_type, entry_id),
                title=title,
                source_type=source.source_type,
                source_priority=source.priority,
                canonical_url=entry_id,
                state="detected",
                source_published_at=published,
                source_metadata={"watch_source": source.name},
            )
        )
    return items


def discover_content(
    sources: list[WatchSource] | None = None,
    fetch_text: callable | None = None,
) -> list[ContentItem]:
    fetch_text = fetch_text or _fetch_text
    discovered: dict[str, ContentItem] = {}
    for source in sources or default_watch_sources():
        raw = fetch_text(source.url)
        if source.kind == "atom":
            items = _parse_atom_listing(source, raw)
        else:
            items = _parse_html_listing(source, raw)
        for item in items:
            existing = discovered.get(item.source_id)
            if existing is None or item.source_priority > existing.source_priority:
                discovered[item.source_id] = item
    return sorted(
        discovered.values(),
        key=lambda item: (-item.source_priority, item.source_published_at or datetime.now(timezone.utc).isoformat(), item.title),
    )


def queue_discovered_content(
    store: JobStore,
    sources: list[WatchSource] | None = None,
    fetch_text: callable | None = None,
) -> list[ContentItem]:
    queued: list[ContentItem] = []
    for item in discover_content(sources=sources, fetch_text=fetch_text):
        try:
            existing = store.get_item(item.source_id)
        except KeyError:
            existing = None
        if existing:
            continue
        queued.append(store.upsert_item(item.model_copy(update={"state": "queued"})))
    return queued
