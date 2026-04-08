from paper2video.cli import build_parser


def test_parser_accepts_url():
    p = build_parser()
    args = p.parse_args(["https://example.com/a"])
    assert args.source == "https://example.com/a"
    assert args.no_search is False


def test_parser_flags():
    p = build_parser()
    args = p.parse_args(["a.pdf", "--no-search", "--fake-tts", "--out", "custom"])
    assert args.no_search is True
    assert args.fake_tts is True
    assert args.out == "custom"
