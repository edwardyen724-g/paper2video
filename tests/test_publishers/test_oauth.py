import json
import time
from pathlib import Path

from paper2video.publishers._oauth import OAuthTokenStore


def test_save_and_load_tokens(tmp_path):
    store = OAuthTokenStore("youtube", tmp_path)
    store.save_tokens("access-123", "refresh-456", time.time() + 3600)
    tokens = store.load_tokens()
    assert tokens is not None
    assert tokens["access_token"] == "access-123"
    assert tokens["refresh_token"] == "refresh-456"


def test_load_tokens_returns_none_when_missing(tmp_path):
    store = OAuthTokenStore("youtube", tmp_path)
    assert store.load_tokens() is None


def test_is_expired_returns_true_when_no_tokens(tmp_path):
    store = OAuthTokenStore("youtube", tmp_path)
    assert store.is_expired() is True


def test_is_expired_returns_false_when_fresh(tmp_path):
    store = OAuthTokenStore("youtube", tmp_path)
    store.save_tokens("a", "r", time.time() + 3600)
    assert store.is_expired() is False


def test_is_expired_returns_true_within_buffer(tmp_path):
    store = OAuthTokenStore("youtube", tmp_path)
    # Expires in 200 seconds, but buffer is 300 → expired
    store.save_tokens("a", "r", time.time() + 200)
    assert store.is_expired(buffer_sec=300) is True


def test_save_tokens_with_extra(tmp_path):
    store = OAuthTokenStore("tiktok", tmp_path)
    store.save_tokens("a", "r", time.time() + 3600, extra={"open_id": "user-1"})
    tokens = store.load_tokens()
    assert tokens["open_id"] == "user-1"
