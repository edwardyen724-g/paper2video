from pathlib import Path
from paper2video.ingest import extract_from_html, extract_from_file, IngestedDoc

FIXTURE = Path(__file__).parent / "fixtures" / "sample_article.html"


def test_extract_from_html_returns_clean_text():
    html = FIXTURE.read_text(encoding="utf-8")
    doc = extract_from_html(html, source_url="https://example.com/a")
    assert isinstance(doc, IngestedDoc)
    assert "first paragraph" in doc.text
    assert "nav stuff" not in doc.text
    assert "footer junk" not in doc.text
    assert doc.source_url == "https://example.com/a"


def test_extract_from_file_dispatches_on_suffix(tmp_path):
    html_copy = tmp_path / "a.html"
    html_copy.write_bytes(FIXTURE.read_bytes())
    doc = extract_from_file(html_copy)
    assert "first paragraph" in doc.text
