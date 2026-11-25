"""Person Re-Identification (Re-ID) and the cross-camera worker registry.

Encoder: LMBN-n (Lightweight Multi-Branch Network, OSNet backbone) trained on Market-1501,
exported to ONNX and executed with onnxruntime. Produces a 3584-d appearance embedding per
person crop; identities are compared with cosine similarity.

The registry is deliberately conservative: a new track is linked to an existing worker ID only
when the similarity is above a threshold AND clearly better than the second-best candidate.
Otherwise a NEW worker ID is created - two different workers are never merged on weak evidence.
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

from backend.database.db import session_scope
from backend.database.models import Worker

log = logging.getLogger("reid")

_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class ReIDEncoder:
    def __init__(self, model_path: Path):
        self.model_path = Path(model_path)
        self.session = None
        self.ready = False
        self.error: str | None = None
        self._lock = threading.Lock()

    def load(self) -> None:
        try:
            import onnxruntime as ort

            if not self.model_path.exists():
                # the model may be shipped split into parts (<25 MB each); join them once
                parts = sorted(self.model_path.parent.glob(self.model_path.name + ".part*"))
                if parts:
                    tmp = self.model_path.with_suffix(".joining")
                    with open(tmp, "wb") as out:
                        for p in parts:
                            out.write(p.read_bytes())
                    tmp.replace(self.model_path)
                    log.info("Re-ID model assembled from %d parts", len(parts))
            if not self.model_path.exists():
                raise FileNotFoundError(f"Re-ID model not found: {self.model_path}")
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 2
            self.session = ort.InferenceSession(str(self.model_path), sess_options=opts,
                                                providers=["CPUExecutionProvider"])
            self.input_name = self.session.get_inputs()[0].name
            self.embed(np.zeros((400, 200, 3), np.uint8), np.array([[0, 0, 200, 400]], np.float32))
            self.ready = True
            log.info("Re-ID encoder ready (%s)", self.model_path.name)
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            log.exception("Re-ID encoder failed to load - tracking continues without cross-camera Re-ID")

    def embed(self, frame: np.ndarray, boxes: np.ndarray) -> np.ndarray:
        crops = []
        h, w = frame.shape[:2]
        for x1, y1, x2, y2 in boxes.astype(int):
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                crop = np.zeros((384, 128, 3), np.uint8)
            crop = cv2.resize(crop, (128, 384), interpolation=cv2.INTER_LINEAR)
            crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            crops.append(((crop - _MEAN) / _STD).transpose(2, 0, 1))
        batch = np.stack(crops).astype(np.float32)
        with self._lock:
            feats = self.session.run(None, {self.input_name: batch})[0]
        norms = np.linalg.norm(feats, axis=1, keepdims=True) + 1e-12
        return feats / norms


@dataclass
class WorkerEntry:
    worker_id: int
    code: str
    embedding: np.ndarray | None
    last_seen: float
    last_camera: int
    n_embeddings: int = 0
    active: dict = field(default_factory=dict)  # camera_id -> track_id currently showing this worker
    cameras: set = field(default_factory=set)
    last_db_sync: float = 0.0


class WorkerRegistry:
    """Global (all cameras) mapping of tracks to temporary worker IDs."""

    def __init__(self):
        self._lock = threading.RLock()
        self.workers: dict[int, WorkerEntry] = {}

    # --------------------------------------------------------------- creation
    def _create_worker(self, camera_id: int, emb: np.ndarray | None, now: float) -> WorkerEntry:
        with session_scope() as s:
            w = Worker(code="PENDING", first_camera_id=camera_id, last_camera_id=camera_id, cameras_seen=[camera_id])
            s.add(w)
            s.flush()
            w.code = f"W-{100 + w.id}"
            wid, code = w.id, w.code
        entry = WorkerEntry(wid, code, emb, now, camera_id, 1 if emb is not None else 0, cameras={camera_id})
        self.workers[wid] = entry
        return entry

    # --------------------------------------------------------------- matching
    def resolve(self, camera_id: int, track_id: int, emb: np.ndarray | None, settings: dict) -> tuple[WorkerEntry, bool, float]:
        """Return (worker, matched_existing, similarity)."""
        now = time.time()
        with self._lock:
            best, best_sim, second = None, -1.0, -1.0
            if emb is not None and settings.get("reid_enabled", True):
                memory = float(settings.get("reid_memory_minutes", 30)) * 60
                for entry in self.workers.values():
                    if entry.embedding is None or now - entry.last_seen > memory:
                        continue
                    # the same worker cannot be two different live tracks at the same moment
                    # (a worker visible on another live track within the last 1.5 s is excluded)
                    if entry.active and now - entry.last_seen < 1.5:
                        if any(cid != camera_id or tid != track_id for cid, tid in entry.active.items()):
                            continue
                    sim = float(np.dot(entry.embedding, emb))
                    if sim > best_sim:
                        second, best_sim, best = best_sim, sim, entry
                    elif sim > second:
                        second = sim
            th = float(settings.get("reid_similarity_threshold", 0.72))
            margin = float(settings.get("reid_margin", 0.06))
            if best is not None and best_sim >= th and (best_sim - max(second, 0.0) >= margin or second < th - margin):
                best.active[camera_id] = track_id
                best.last_seen = now
                prev_cam = best.last_camera
                best.last_camera = camera_id
                best.cameras.add(camera_id)
                self._sync_db(best, force=True)
                log.info("Re-ID: track %s on camera %s matched %s (similarity %.2f, 2nd %.2f, previous camera %s)",
                         track_id, camera_id, best.code, best_sim, second, prev_cam)
                return best, True, best_sim
            entry = self._create_worker(camera_id, emb, now)
            entry.active[camera_id] = track_id
            if best is not None:
                log.info("Re-ID: new worker %s on camera %s (best existing %s similarity %.2f, threshold %.2f)",
                         entry.code, camera_id, best.code, best_sim, th)
            else:
                log.info("Re-ID: new worker %s on camera %s (%s)", entry.code, camera_id,
                         "no usable appearance crop" if emb is None else "no previous workers to compare")
            return entry, False, best_sim

    def update(self, worker_id: int, camera_id: int, emb: np.ndarray | None) -> None:
        now = time.time()
        with self._lock:
            entry = self.workers.get(worker_id)
            if entry is None:
                return
            entry.last_seen = now
            entry.last_camera = camera_id
            if emb is not None:
                if entry.embedding is None:
                    entry.embedding = emb
                else:
                    alpha = 0.15 if entry.n_embeddings > 5 else 0.35
                    e = (1 - alpha) * entry.embedding + alpha * emb
                    entry.embedding = e / (np.linalg.norm(e) + 1e-12)
                entry.n_embeddings += 1
            self._sync_db(entry)

    def release(self, worker_id: int, camera_id: int, track_id: int) -> None:
        with self._lock:
            entry = self.workers.get(worker_id)
            if entry and entry.active.get(camera_id) == track_id:
                del entry.active[camera_id]
                self._sync_db(entry, force=True)

    def _sync_db(self, entry: WorkerEntry, force: bool = False) -> None:
        now = time.time()
        if not force and now - entry.last_db_sync < 10:
            return
        entry.last_db_sync = now
        try:
            with session_scope() as s:
                w = s.get(Worker, entry.worker_id)
                if w:
                    w.last_seen = datetime.fromtimestamp(entry.last_seen).replace(microsecond=0)
                    w.last_camera_id = entry.last_camera
                    w.cameras_seen = sorted(entry.cameras)
        except Exception:  # noqa: BLE001
            log.exception("Worker DB sync failed")

    def prune(self, max_age_seconds: float) -> None:
        now = time.time()
        with self._lock:
            for wid in [w for w, e in self.workers.items() if not e.active and now - e.last_seen > max_age_seconds]:
                del self.workers[wid]

    def stats(self) -> dict:
        with self._lock:
            return {
                "workers_in_memory": len(self.workers),
                "workers_active": sum(1 for e in self.workers.values() if e.active),
            }
