"""Violation registration with duplicate prevention and notification cooldown.

Rules (all configurable in Settings):
* An *incident* is (worker ID, violation type). While an incident is active, further sightings of the
  same violation - on the same camera or any other camera - update the existing record instead of
  creating a new one, and no new alert is sent.
* An incident stays active until it has not been observed for ``duplicate_window_seconds``, or until
  a supervisor closes the violation record.
* Alerts for the same worker + violation type are rate-limited by ``notification_cooldown_seconds``.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from backend.config import VIOLATION_TYPES, VIOLATIONS_DIR
from backend.database.db import session_scope
from backend.database.models import Violation
from backend.events import bus
from backend.notifications.dispatcher import get_dispatcher

log = logging.getLogger("violations")

LIVE_TEXT = {"helmet": "NO HELMET DETECTED", "vest": "NO SAFETY VEST DETECTED", "shoes": "NO SAFETY SHOES DETECTED"}


@dataclass
class Incident:
    violation_id: int
    code: str
    worker_id: int
    item: str
    first_seen: float
    last_seen: float
    last_db_update: float
    cameras: set = field(default_factory=set)
    occurrences: int = 1


class ViolationManager:
    def __init__(self):
        self._lock = threading.RLock()
        self.incidents: dict[tuple[int, str], Incident] = {}
        self.last_notified: dict[tuple[int, str], float] = {}
        self.suppressed_duplicates = 0

    # -------------------------------------------------------------- public API
    def report(self, *, worker_id: int, worker_code: str, item: str, confidence: float, camera: dict,
               frame: np.ndarray, render_evidence, settings: dict) -> dict | None:
        """Called by camera workers while a confirmed violation is visible. Returns the new violation (if any)."""
        now = time.time()
        key = (worker_id, item)
        window = float(settings.get("duplicate_window_seconds", 300))
        with self._lock:
            inc = self.incidents.get(key)
            if inc and now - inc.last_seen <= window:
                self._touch(inc, camera, now)
                return None
            if inc:
                del self.incidents[key]
            violation = self._create(worker_id, worker_code, item, confidence, camera, frame, render_evidence, settings, now)
            self.incidents[key] = Incident(violation["id"], violation["code"], worker_id, item, now, now, now,
                                           {camera["id"]})
            cooldown = float(settings.get("notification_cooldown_seconds", 300))
            last = self.last_notified.get(key)
            if last is None or now - last >= cooldown:
                image_path = VIOLATIONS_DIR / violation["evidence_path"] if violation.get("evidence_path") else None
                if get_dispatcher().enqueue(violation, image_path):
                    self.last_notified[key] = now
            else:
                log.info("Alert for %s suppressed by notification cooldown (%.0fs left)",
                         violation["code"], cooldown - (now - last))
        return violation

    def on_violation_closed(self, violation_id: int) -> None:
        with self._lock:
            for key, inc in list(self.incidents.items()):
                if inc.violation_id == violation_id:
                    del self.incidents[key]

    def expire(self, settings: dict) -> None:
        window = float(settings.get("duplicate_window_seconds", 300))
        now = time.time()
        with self._lock:
            for key, inc in list(self.incidents.items()):
                if now - inc.last_seen > window:
                    del self.incidents[key]

    def active_incidents(self) -> list[dict]:
        with self._lock:
            return [{"violation_id": i.violation_id, "code": i.code, "worker_id": i.worker_id, "item": i.item,
                     "cameras": sorted(i.cameras), "occurrences": i.occurrences,
                     "last_seen": datetime.fromtimestamp(i.last_seen).isoformat(timespec="seconds")}
                    for i in self.incidents.values()]

    # -------------------------------------------------------------- internals
    def _touch(self, inc: Incident, camera: dict, now: float) -> None:
        new_camera = camera["id"] not in inc.cameras
        reappeared = now - inc.last_seen > 10  # seen again after a gap
        inc.last_seen = now
        if new_camera or reappeared:
            inc.cameras.add(camera["id"])
            inc.occurrences += 1
            self.suppressed_duplicates += 1
            self._update_db(inc, camera)
            msg = (f"{inc.code}: same worker seen again on {camera['name']} ({camera.get('location', '')}) - "
                   "linked to the existing violation, no duplicate alert")
            log.info(msg)
            bus.publish("duplicate_suppressed", {"violation_id": inc.violation_id, "camera": camera["name"]},
                        activity=msg, level="warning")
        elif now - inc.last_db_update > 5:
            self._update_db(inc, camera)

    def _update_db(self, inc: Incident, camera: dict) -> None:
        inc.last_db_update = time.time()
        try:
            with session_scope() as s:
                v = s.get(Violation, inc.violation_id)
                if v is None:
                    return
                v.last_seen_at = datetime.now().replace(microsecond=0)
                v.occurrences = inc.occurrences
                involved = list(v.cameras_involved or [])
                if camera["name"] not in involved:
                    involved.append(camera["name"])
                    v.cameras_involved = involved
                data = v.to_dict()
            bus.publish("violation_updated", data)
        except Exception:  # noqa: BLE001
            log.exception("Failed to update violation %s", inc.code)

    def _create(self, worker_id, worker_code, item, confidence, camera, frame, render_evidence, settings, now) -> dict:
        detected = datetime.fromtimestamp(now).replace(microsecond=0)
        label = VIOLATION_TYPES.get(item, f"Missing {item.title()}")
        with session_scope() as s:
            v = Violation(
                worker_id=worker_id, worker_code=worker_code, violation_type=item, violation_label=label,
                camera_id=camera["id"], camera_name=camera["name"], location=camera.get("location", ""),
                tower=camera.get("tower", ""), floor=camera.get("floor", ""), detected_at=detected,
                last_seen_at=detected, confidence=float(confidence), status="Open",
                cameras_involved=[camera["name"]],
            )
            s.add(v)
            s.flush()
            v.code = f"V-{v.id:06d}"
            vid, code = v.id, v.code

        rel = ""
        try:
            day_dir = VIOLATIONS_DIR / detected.strftime("%Y-%m-%d")
            day_dir.mkdir(parents=True, exist_ok=True)
            fname = f"{code}_{item}_{worker_code}.jpg"
            banner = [
                f"PPE VIOLATION  {code}  -  {LIVE_TEXT.get(item, label.upper())}  ({round(confidence * 100)}%)",
                f"Worker {worker_code}  |  {camera['name']}  |  {camera.get('location', '')}  |  "
                f"{detected.strftime('%Y-%m-%d %H:%M:%S')}",
            ]
            img = render_evidence(frame, banner)
            quality = int(settings.get("evidence_jpeg_quality", 90))
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
            if ok:
                (day_dir / fname).write_bytes(buf.tobytes())
                rel = f"{detected.strftime('%Y-%m-%d')}/{fname}"
        except Exception:  # noqa: BLE001
            log.exception("Evidence capture failed for %s", code)

        with session_scope() as s:
            v = s.get(Violation, vid)
            v.evidence_path = rel
            data = v.to_dict()
        msg = f"{code}: {label} - worker {worker_code} on {camera['name']} ({camera.get('location', '')})"
        log.warning("VIOLATION REGISTERED %s", msg)
        bus.publish("violation_created", data, activity=msg, level="error")
        return data


violation_manager = ViolationManager()


def evidence_file(rel: str) -> Path:
    return VIOLATIONS_DIR / rel
