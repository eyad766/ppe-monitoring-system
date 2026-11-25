"""Duplicate-prevention / database registration tests.

Run:  .venv\\Scripts\\python.exe -m tests.test_violation_rules
Uses a temporary database and evidence folder.
"""
import os
import tempfile
import time
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
os.environ["DATABASE_URL"] = f"sqlite:///{(tmp / 'test.db').as_posix()}"

import numpy as np  # noqa: E402

from backend.database.db import init_db, session_scope  # noqa: E402

init_db()
import backend.violations.manager as vm  # noqa: E402
from backend.config import DEFAULT_SETTINGS  # noqa: E402
from backend.database.models import Violation, Worker  # noqa: E402

with session_scope() as _s:
    _s.add_all([Worker(id=1, code="W-101"), Worker(id=2, code="W-102")])

vm.VIOLATIONS_DIR = tmp
mgr = vm.ViolationManager()
frame = np.zeros((360, 640, 3), np.uint8)
cam1 = {"id": 1, "name": "Camera 01", "location": "Tower B - Level 8"}
cam2 = {"id": 2, "name": "Camera 02", "location": "Tower B - Level 7"}
settings = dict(DEFAULT_SETTINGS, duplicate_window_seconds=2, notification_cooldown_seconds=0)
render = lambda f, banner: f  # noqa: E731


def report(worker, item, cam):
    return mgr.report(worker_id=worker, worker_code=f"W-{100 + worker}", item=item, confidence=0.9,
                      camera=cam, frame=frame, render_evidence=render, settings=settings)


def count():
    with session_scope() as s:
        return s.query(Violation).count()


passed = 0


def check(cond, msg):
    global passed
    assert cond, msg
    passed += 1
    print("PASS", msg)


v1 = report(1, "helmet", cam1)
check(v1 is not None and count() == 1, "first violation is registered in the database")
check((tmp / v1["evidence_url"].replace("/evidence/", "")).exists(), "evidence image is saved")
for _ in range(20):
    report(1, "helmet", cam1)
check(count() == 1, "repeated detections of the same incident do not create duplicates")
time.sleep(0.2)
check(report(1, "helmet", cam2) is None and count() == 1, "same worker on another camera is linked to the existing violation")
with session_scope() as s:
    v = s.get(Violation, v1["id"])
    check("Camera 02" in v.cameras_involved, "existing violation records the second camera")
check(report(1, "vest", cam1) is not None and count() == 2, "a different violation type is a separate violation")
check(report(2, "helmet", cam1) is not None and count() == 3, "a different worker is never merged into another worker's violation")
time.sleep(2.3)
check(report(1, "helmet", cam1) is not None and count() == 4, "after the duplicate window expires a new violation is registered")
mgr.on_violation_closed(count())
check(report(1, "helmet", cam1) is not None and count() == 5, "after a supervisor closes it, a new occurrence is a new violation")

# notification payload carries the evidence photo path
captured = {}
vm.get_dispatcher = lambda: type("D", (), {"enqueue": lambda self, v, p: captured.update(v=v, p=p) or True})()
report(2, "vest", cam2)
check(captured.get("p") is not None and Path(captured["p"]).exists(), "Telegram alert receives the evidence photo")
from backend.notifications.telegram import format_caption  # noqa: E402
cap = format_caption(captured["v"])
check(all(x in cap for x in ("Worker ID", "W-102", "Camera 02", "Tower B - Level 7", "OPEN", "Missing Safety Vest")),
      "alert text contains worker, violation, camera, location, time and status")
print(cap)
print(f"\nAll {passed} checks passed.")
