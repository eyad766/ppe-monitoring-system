"""Offline harness: runs the real detection/tracking/Re-ID/violation pipeline frame-by-frame on a video.
Usage: python -m tests.pipeline_harness <video>   (uses a temporary database)"""
import os, sys, tempfile, time, logging
tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/test.db"
import cv2
from backend.logging_setup import setup_logging
setup_logging(logging.INFO)
from backend.database.db import init_db
init_db()
from backend import settings_store
from backend.camera.manager import CameraManager
from backend.camera.worker import CameraWorker
from backend.database.db import session_scope
from backend.database.models import Violation

video = sys.argv[1]; step = int(sys.argv[2]) if len(sys.argv) > 2 else 2
mgr = CameraManager(); mgr.services.engine.load(); mgr.services.reid.load()
cam = {"id": 1, "name": "Camera 01", "location": "Tower B - Level 8", "tower": "Tower B", "floor": "Level 8",
       "source_type": "file", "source": video}
w = CameraWorker(cam, mgr.services)
import threading
threading.Thread(target=w._reid_loop, daemon=True).start()
s = settings_store.get_settings()
cap = cv2.VideoCapture(video); fps = cap.get(cv2.CAP_PROP_FPS) or 15
i = 0; last_line = None; t0 = time.time()
while True:
    ok, f = cap.read()
    if not ok: break
    # real-time playback: skip frames the AI could not keep up with (like a live camera)
    if i / fps < time.time() - t0:
        i += 1; continue
    while i / fps > time.time() - t0: time.sleep(0.005)
    if True:
        w._process(f, s)
        items, _ = w._overlay
        line = " ; ".join(f"T{it.track_id}:{it.title}:{it.status}" for it in items)
        if line != last_line:
            print(f"t={i/fps:5.1f}s  {line}")
            last_line = line
    i += 1
with session_scope() as db:
    for v in db.query(Violation).all():
        print(v.code, v.worker_code, v.violation_type, round(v.confidence, 2), "occurrences", v.occurrences)
