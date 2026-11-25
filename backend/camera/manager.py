"""Shared AI services and the camera manager (start/stop/list running cameras)."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from backend.camera.worker import CameraWorker
from backend.config import INFERENCE_DEVICE, PERSON_MODEL_PATH, PPE_MODEL_PATH, REID_MODEL_PATH
from backend.database.db import session_scope
from backend.database.models import Camera
from backend.detection.ppe_detector import PPEDetectionEngine
from backend.tracking.reid import ReIDEncoder, WorkerRegistry
from backend.violations.manager import ViolationManager, violation_manager

log = logging.getLogger("camera.manager")


@dataclass
class Services:
    engine: PPEDetectionEngine
    reid: ReIDEncoder
    registry: WorkerRegistry
    violations: ViolationManager


class CameraManager:
    def __init__(self):
        self.services = Services(
            engine=PPEDetectionEngine(PPE_MODEL_PATH, PERSON_MODEL_PATH, INFERENCE_DEVICE),
            reid=ReIDEncoder(REID_MODEL_PATH),
            registry=WorkerRegistry(),
            violations=violation_manager,
        )
        self.workers: dict[int, CameraWorker] = {}
        self._lock = threading.RLock()
        self.models_loading = False

    def load_models_async(self, then_autostart: bool = True) -> None:
        def _load():
            self.models_loading = True
            self.services.engine.load()
            self.services.reid.load()
            self.models_loading = False
            if then_autostart:
                self.autostart()

        threading.Thread(target=_load, name="model-loader", daemon=True).start()

    def autostart(self) -> None:
        with session_scope() as s:
            ids = [c.id for c in s.query(Camera).filter_by(enabled=True, auto_start=True).all()]
        for cid in ids:
            try:
                self.start(cid)
            except Exception:  # noqa: BLE001
                log.exception("Auto-start failed for camera %s", cid)

    def start(self, camera_id: int) -> dict:
        with self._lock:
            w = self.workers.get(camera_id)
            if w and w.running:
                return w.snapshot()
            with session_scope() as s:
                cam = s.get(Camera, camera_id)
                if cam is None:
                    raise KeyError(f"Camera {camera_id} not found")
                if not cam.enabled:
                    raise ValueError("Camera is disabled")
                data = cam.to_dict()
            if data["source_type"] == "webcam":
                for other in self.workers.values():
                    if other.running and other.camera["source_type"] == "webcam" and other.camera["source"] == data["source"]:
                        raise ValueError(f"Webcam {data['source']} is already used by {other.camera['name']}")
            worker = CameraWorker(data, self.services)
            self.workers[camera_id] = worker
            worker.start()
            log.info("Camera started: %s (%s %s)", data["name"], data["source_type"], data["source"])
            return worker.snapshot()

    def stop(self, camera_id: int) -> dict:
        with self._lock:
            w = self.workers.get(camera_id)
            if not w:
                return {"camera_id": camera_id, "status": "stopped"}
            w.stop()
            log.info("Camera stopped: %s", w.camera["name"])
            return w.snapshot()

    def restart_if_running(self, camera_id: int) -> None:
        w = self.workers.get(camera_id)
        if w and w.running:
            self.stop(camera_id)
            self.start(camera_id)

    def remove(self, camera_id: int) -> None:
        with self._lock:
            self.stop(camera_id)
            self.workers.pop(camera_id, None)

    def status(self, camera_id: int) -> dict:
        w = self.workers.get(camera_id)
        if w is None:
            return {"camera_id": camera_id, "status": "stopped", "error": None, "persons": 0, "ai_fps": 0,
                    "capture_fps": 0, "infer_ms": 0, "compliant": 0, "violations": 0, "unknown": 0,
                    "resolution": None, "uptime_seconds": 0}
        return w.snapshot()

    def busy_webcams(self) -> set[int]:
        return {int(w.camera["source"]) for w in self.workers.values()
                if w.running and w.camera["source_type"] == "webcam"}

    def shutdown(self) -> None:
        for cid in list(self.workers):
            try:
                self.stop(cid)
            except Exception:  # noqa: BLE001
                pass


manager = CameraManager()
