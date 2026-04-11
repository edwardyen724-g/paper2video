from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError

from .types import ContentItem, SocialDraft


class ReviewClient:
    def send_draft(self, draft: SocialDraft) -> str:
        raise NotImplementedError


@dataclass
class FakeTelegramReviewClient(ReviewClient):
    sent_drafts: list[SocialDraft] = field(default_factory=list)

    def send_draft(self, draft: SocialDraft) -> str:
        self.sent_drafts.append(draft)
        return f"fake-message-{len(self.sent_drafts)}"


class TelegramReviewClient(ReviewClient):
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id

    @property
    def _base_url(self) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}"

    def _post_json(self, method: str, payload: dict) -> dict:
        req = urllib.request.Request(
            f"{self._base_url}/{method}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_updates(self, offset: int | None = None, timeout: int = 0) -> list[dict]:
        params = {}
        if offset is not None:
            params["offset"] = str(offset)
        if timeout:
            params["timeout"] = str(timeout)
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        with urllib.request.urlopen(f"{self._base_url}/getUpdates{query}", timeout=30 + timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return list(payload.get("result", []))

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        try:
            self._post_json("answerCallbackQuery", payload)
        except HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if "query is too old" in body or "query ID is invalid" in body:
                return
            raise

    def send_text(self, text: str, chat_id: str | None = None) -> str:
        payload = {"chat_id": chat_id or self.chat_id, "text": text}
        response = self._post_json("sendMessage", payload)
        return str(response.get("result", {}).get("message_id", ""))

    def send_draft(self, draft: SocialDraft) -> str:
        message = (
            f"*{draft.item.title}*\n"
            f"{draft.item.canonical_url}\n\n"
            f"{draft.script.summary}"
        )
        keyboard = {
            "inline_keyboard": [[
                {"text": "Approve", "callback_data": f"approve:{draft.item.source_id}"},
                {"text": "Revise", "callback_data": f"revise:{draft.item.source_id}"},
                {"text": "Skip", "callback_data": f"skip:{draft.item.source_id}"},
            ]]
        }
        with Path(draft.review_video_path).open("rb") as handle:
            boundary = "paper2video-boundary"
            body_parts: list[bytes] = []
            fields = {
                "chat_id": self.chat_id,
                "caption": message,
                "parse_mode": "Markdown",
                "reply_markup": json.dumps(keyboard),
            }
            for key, value in fields.items():
                body_parts.append(f"--{boundary}\r\n".encode())
                body_parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode("utf-8"))
            video_bytes = handle.read()
            body_parts.append(f"--{boundary}\r\n".encode())
            body_parts.append(
                b'Content-Disposition: form-data; name="video"; filename="review.mp4"\r\n'
                b"Content-Type: video/mp4\r\n\r\n"
            )
            body_parts.append(video_bytes)
            body_parts.append(f"\r\n--{boundary}--\r\n".encode())
            req = urllib.request.Request(
                f"{self._base_url}/sendVideo",
                data=b"".join(body_parts),
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                response = json.loads(resp.read().decode("utf-8"))
        return str(response.get("result", {}).get("message_id", ""))


def parse_telegram_callback(update: dict) -> tuple[str, str, str]:
    callback = update.get("callback_query") or {}
    data = str(callback.get("data", ""))
    action, _, source_id = data.partition(":")
    message_text = str((callback.get("message") or {}).get("text", ""))
    return action, source_id, message_text


def parse_telegram_message(update: dict) -> tuple[str, str, str]:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    return str(chat.get("id", "")), str(message.get("text", "")), str(message.get("message_id", ""))
