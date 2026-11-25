"""Telegram Bot notifications (sendPhoto with caption, falling back to sendMessage)."""
from __future__ import annotations

import html
import logging
from datetime import datetime
from pathlib import Path

import httpx

log = logging.getLogger("telegram")
API = "https://api.telegram.org/bot{token}/{method}"


def format_caption(v: dict) -> str:
    detected = v.get("detected_at")
    try:
        dt = datetime.fromisoformat(detected) if detected else datetime.now()
    except ValueError:
        dt = datetime.now()
    e = html.escape
    return (
        "🚨 <b>PPE VIOLATION DETECTED</b>\n\n"
        f"<b>Violation ID:</b> {e(v.get('code', ''))}\n"
        f"<b>Worker ID:</b> {e(v.get('worker_code', ''))}\n"
        f"<b>Violation:</b> {e(v.get('violation_label', ''))}\n"
        f"<b>Camera:</b> {e(v.get('camera_name', ''))}\n"
        f"<b>Location:</b> {e(v.get('location', '') or '-')}\n"
        f"<b>Date:</b> {dt.strftime('%Y-%m-%d')}\n"
        f"<b>Time:</b> {dt.strftime('%I:%M:%S %p')}\n"
        f"<b>Confidence:</b> {round(float(v.get('confidence', 0)) * 100)}%\n"
        f"<b>Status:</b> {e(str(v.get('status', 'Open')).upper())}"
    )


class TelegramNotifier:
    name = "telegram"

    def __init__(self, token: str, chat_id: str, send_photo: bool = True, timeout: float = 20.0):
        self.token = token.strip()
        self.chat_id = str(chat_id).strip()
        self.send_photo = send_photo
        self.timeout = timeout

    def _post(self, method: str, **kwargs) -> dict:
        url = API.format(token=self.token, method=method)
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(url, **kwargs)
        try:
            data = r.json()
        except ValueError:
            data = {"ok": False, "description": f"HTTP {r.status_code}"}
        if not data.get("ok"):
            raise RuntimeError(data.get("description") or f"Telegram error (HTTP {r.status_code})")
        return data

    def send_text(self, text: str) -> None:
        self._post("sendMessage", data={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"})

    def send_violation(self, violation: dict, image_path: Path | None) -> None:
        caption = format_caption(violation)
        if self.send_photo and image_path and Path(image_path).exists():
            with open(image_path, "rb") as fh:
                self._post("sendPhoto", data={"chat_id": self.chat_id, "caption": caption, "parse_mode": "HTML"},
                           files={"photo": (Path(image_path).name, fh, "image/jpeg")})
        else:
            self.send_text(caption)

    def test(self) -> dict:
        me = self._post("getMe")
        bot = me.get("result", {}).get("username", "?")
        self.send_text(
            "✅ <b>PPE Monitoring System</b>\nTelegram notifications are configured correctly.\n"
            f"Bot: @{html.escape(bot)}\nTime: {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}"
        )
        return {"bot": bot}
