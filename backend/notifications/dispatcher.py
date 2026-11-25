"""Background notification dispatcher. New channels (mobile push, e-mail, SMS...) plug in here."""
from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path

from backend import settings_store
from backend.database.db import session_scope
from backend.database.models import Violation
from backend.events import bus
from backend.notifications.telegram import TelegramNotifier

log = logging.getLogger("notifications")


def build_channels(settings: dict) -> list:
    channels = []
    if settings.get("telegram_enabled") and settings.get("telegram_bot_token") and settings.get("telegram_chat_id"):
        channels.append(TelegramNotifier(settings["telegram_bot_token"], settings["telegram_chat_id"],
                                         settings.get("telegram_send_photo", True)))
    # Future: channels.append(PushNotifier(...))
    return channels


class NotificationDispatcher:
    def __init__(self):
        self._q: queue.Queue = queue.Queue(maxsize=1000)
        self._thread = threading.Thread(target=self._run, name="notifications", daemon=True)
        self._thread.start()

    def enqueue(self, violation: dict, image_path: Path | None) -> bool:
        channels = build_channels(settings_store.get_settings())
        if not channels:
            return False
        try:
            self._q.put_nowait((violation, image_path))
            return True
        except queue.Full:
            log.error("Notification queue full - dropping alert for %s", violation.get("code"))
            return False

    def _run(self) -> None:
        while True:
            violation, image_path = self._q.get()
            errors, sent = [], []
            for ch in build_channels(settings_store.get_settings()):
                for attempt in range(3):
                    try:
                        ch.send_violation(violation, image_path)
                        sent.append(ch.name)
                        break
                    except Exception as exc:  # noqa: BLE001
                        if attempt == 2:
                            errors.append(f"{ch.name}: {exc}")
                            log.error("Notification via %s failed for %s: %s", ch.name, violation.get("code"), exc)
                        else:
                            threading.Event().wait(2 * (attempt + 1))
            try:
                with session_scope() as s:
                    v = s.get(Violation, violation["id"])
                    if v:
                        v.notified = bool(sent)
                        v.notification_error = "; ".join(errors)
                        data = v.to_dict()
                bus.publish("violation_updated", data,
                            activity=(f"Alert sent via {', '.join(sent)} for {violation['code']}" if sent
                                      else f"Alert FAILED for {violation['code']}: {'; '.join(errors)}"),
                            level="info" if sent else "error")
            except Exception:  # noqa: BLE001
                log.exception("Failed to store notification result")


dispatcher: NotificationDispatcher | None = None


def get_dispatcher() -> NotificationDispatcher:
    global dispatcher
    if dispatcher is None:
        dispatcher = NotificationDispatcher()
    return dispatcher
