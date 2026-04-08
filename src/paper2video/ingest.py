from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import urllib.request


@dataclass
class IngestedDoc:
    text: str
    title: str
    source_url: str


def extract_from_html(html: str, source_url: str = "") -> IngestedDoc:
    import trafilatura
    text = trafilatura.extract(html, include_comments=False, include_tables=True) or ""
    meta = trafilatura.extract_metadata(html)
    title = meta.title if meta and meta.title else ""
    return IngestedDoc(text=text.strip(), title=title, source_url=source_url)


def extract_from_pdf(path: Path) -> IngestedDoc:
    import pymupdf  # type: ignore
    doc = pymupdf.open(path)
    try:
        parts = [page.get_text() for page in doc]
    finally:
        doc.close()
    text = "\n\n".join(parts).strip()
    return IngestedDoc(text=text, title=path.stem, source_url=str(path))


def extract_from_file(path: Path) -> IngestedDoc:
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        return extract_from_pdf(path)
    html = path.read_text(encoding="utf-8", errors="replace")
    return extract_from_html(html, source_url=str(path))


def extract_from_url(url: str, timeout: float = 30.0) -> IngestedDoc:
    req = urllib.request.Request(url, headers={"User-Agent": "paper2video/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    if raw[:4] == b"%PDF":
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(raw)
            tmp = Path(f.name)
        try:
            doc = extract_from_pdf(tmp)
        finally:
            tmp.unlink(missing_ok=True)
        return IngestedDoc(text=doc.text, title=doc.title, source_url=url)
    html = raw.decode("utf-8", errors="replace")
    return extract_from_html(html, source_url=url)
