"""Shared OAuth2 token storage and one-time browser-based authorization flow."""
from __future__ import annotations

import json
import time
import threading
import urllib.parse
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path


class OAuthTokenStore:
    """File-based OAuth2 token persistence in .tokens/{platform}.json."""

    def __init__(self, platform: str, tokens_dir: Path = Path(".tokens")):
        self.platform = platform
        self.tokens_dir = tokens_dir
        self._path = tokens_dir / f"{platform}.json"

    def save_tokens(
        self,
        access_token: str,
        refresh_token: str,
        expires_at: float,
        *,
        extra: dict | None = None,
    ) -> None:
        self.tokens_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
        }
        if extra:
            data.update(extra)
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_tokens(self) -> dict | None:
        if not self._path.exists():
            return None
        return json.loads(self._path.read_text(encoding="utf-8"))

    def is_expired(self, buffer_sec: float = 300) -> bool:
        tokens = self.load_tokens()
        if tokens is None:
            return True
        return time.time() >= tokens.get("expires_at", 0) - buffer_sec

    def refresh(
        self,
        client_id: str,
        client_secret: str,
        token_url: str,
    ) -> dict:
        """POST to token_url with the stored refresh_token. Returns new token dict."""
        import urllib.request

        tokens = self.load_tokens()
        if tokens is None:
            raise FileNotFoundError(f"No tokens for {self.platform}. Run --setup-oauth {self.platform} first.")
        body = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": client_id,
            "client_secret": client_secret,
        }).encode()
        req = urllib.request.Request(token_url, data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req) as resp:
            new_tokens = json.loads(resp.read())
        expires_in = new_tokens.get("expires_in", 3600)
        self.save_tokens(
            access_token=new_tokens["access_token"],
            refresh_token=new_tokens.get("refresh_token", tokens["refresh_token"]),
            expires_at=time.time() + expires_in,
        )
        return self.load_tokens()  # type: ignore[return-value]


def run_oauth_setup(
    platform: str,
    client_id: str,
    client_secret: str,
    auth_url: str,
    token_url: str,
    scopes: list[str],
    redirect_uri: str = "http://localhost:8080",
    tokens_dir: Path = Path(".tokens"),
) -> dict:
    """Run a one-time interactive OAuth2 authorization code flow.

    1. Open browser to auth_url
    2. Listen on localhost:8080 for the redirect with ?code=
    3. Exchange code for tokens
    4. Save tokens to disk
    """
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
    })
    full_auth_url = f"{auth_url}?{params}"

    auth_code: str | None = None
    error_msg: str | None = None

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            nonlocal auth_code, error_msg
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in qs:
                auth_code = qs["code"][0]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Authorization successful! You can close this tab.")
            elif "error" in qs:
                error_msg = qs["error"][0]
                self.send_response(400)
                self.end_headers()
                self.wfile.write(f"Error: {error_msg}".encode())
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing code parameter.")

        def log_message(self, format, *args):  # noqa: A002
            pass  # suppress HTTP logs

    server = HTTPServer(("localhost", 8080), _Handler)
    server_thread = threading.Thread(target=server.handle_request, daemon=True)
    server_thread.start()

    print(f"\nOpening browser for {platform} OAuth authorization...")
    print(f"If the browser doesn't open, visit:\n{full_auth_url}\n")
    webbrowser.open(full_auth_url)

    server_thread.join(timeout=120)
    server.server_close()

    if error_msg:
        raise RuntimeError(f"OAuth error: {error_msg}")
    if auth_code is None:
        raise RuntimeError("Timed out waiting for OAuth redirect. Try again.")

    # Exchange code for tokens
    import urllib.request
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode()
    req = urllib.request.Request(token_url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req) as resp:
        token_data = json.loads(resp.read())

    store = OAuthTokenStore(platform, tokens_dir)
    expires_in = token_data.get("expires_in", 3600)
    store.save_tokens(
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token", ""),
        expires_at=time.time() + expires_in,
    )
    print(f"Tokens saved to {store._path}")
    return store.load_tokens()  # type: ignore[return-value]
