"""One CameraWorker per running camera.

Two threads per camera:
* capture thread - reads frames at the camera's native rate, draws the latest AI overlay and
  encodes the live MJPEG stream (smooth video even when AI runs slower than the camera).
* AI thread      - takes the newest frame, runs PPE detection -> ByteTrack -> Re-ID -> temporal
  PPE decision -> violation registration.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

import cv2
import numpy as np

from backend import settings_store
from backend.camera.sources import open_source
from backend.database.db import session_scope
from backend.database.models import DetectionStat
from backend.detection.annotator import (AMBER, GREEN, RED, OverlayItem, draw_hud, draw_items, placeholder,
                                         render_evidence)
from backend.events import bus
from backend.tracking.ppe_state import TrackPPEState
from backend.tracking.reid import WorkerEntry
from backend.tracking.tracker import PersonTracker
from backend.violations.manager import LIVE_TEXT

log = logging.getLogger("camera")

ITEM_NAMES = {"helmet": "Helmet", "vest": "Vest", "shoes": "Shoes"}


@dataclass
class TrackInfo:
    track_id: int
    first_t: float
    last_t: float
    box: np.ndarray
    worker: WorkerEntry | None = None
    pending_embs: list = field(default_factory=list)
    last_emb_t: float = 0.0
    drift_count: int = 0
    epoch: int = 0
    last_verified_t: float = 0.0
    ppe: TrackPPEState = field(default_factory=TrackPPEState)


def _iou_max(boxes: np.ndarray) -> np.ndarray:
    """For each box, the max IoU with any other box (used to skip occluded crops for Re-ID)."""
    n = len(boxes)
    out = np.zeros(n, np.float32)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            a, b = boxes[i], boxes[j]
            ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
            iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
            inter = ix * iy
            union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
            out[i] = max(out[i], inter / union if union > 0 else 0)
    return out


class CameraWorker:
    def __init__(self, camera: dict, services):
        self.camera = camera
        self.services = services
        self.status = "stopped"
        self.error: str | None = None
        self._stop = threading.Event()
        self._frame_lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._frame_seq = 0
        self._new_frame = threading.Event()
        self._overlay: tuple[list[OverlayItem], float] = ([], 0.0)
        self.jpeg: bytes | None = None
        self.jpeg_seq = 0
        self.resolution: str | None = None
        self.capture_fps = 0.0
        self.ai_fps = 0.0
        self.infer_ms = 0.0
        self.counts = {"persons": 0, "compliant": 0, "violations": 0, "unknown": 0}
        self.tracks: dict[int, TrackInfo] = {}
        self._tracker: PersonTracker | None = None
        self._tracker_key = None
        self._stats = {"frames": 0, "persons": 0, "compliant": 0, "violation": 0, "unknown": 0}
        self._threads: list[threading.Thread] = []
        self.started_at: float | None = None
        self._reid_jobs: queue.Queue = queue.Queue(maxsize=1)
        self._reid_results: dict[int, tuple] = {}
        self._reid_inflight: set[int] = set()
        self._reid_lock = threading.Lock()

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._stop.clear()
        self.started_at = time.time()
        self._set_status("connecting")
        self._threads = [
            threading.Thread(target=self._capture_loop, name=f"cap-{self.camera['id']}", daemon=True),
            threading.Thread(target=self._ai_loop, name=f"ai-{self.camera['id']}", daemon=True),
            threading.Thread(target=self._reid_loop, name=f"reid-{self.camera['id']}", daemon=True),
        ]
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop.set()
        self._new_frame.set()
        for t in self._threads:
            t.join(timeout=5)
        reg = self.services.registry
        for info in self.tracks.values():
            if info.worker:
                reg.release(info.worker.worker_id, self.camera["id"], info.track_id)
        self.tracks.clear()
        self._flush_stats()
        self._set_status("stopped")
        self.jpeg = self._encode(placeholder("CAMERA STOPPED", f"{self.camera['name']} - {self.camera.get('location', '')}"))
        self.jpeg_seq += 1

    @property
    def running(self) -> bool:
        return not self._stop.is_set() and any(t.is_alive() for t in self._threads)

    def _set_status(self, status: str, error: str | None = None) -> None:
        changed = status != self.status or error != self.error
        self.status, self.error = status, error
        if changed:
            level = {"online": "info", "error": "error", "reconnecting": "warning"}.get(status, "info")
            msg = f"{self.camera['name']} ({self.camera.get('location', '')}): {status.upper()}"
            if error:
                msg += f" - {error}"
            bus.publish("camera_status", self.snapshot(), activity=msg, level=level)

    def snapshot(self) -> dict:
        return {
            "camera_id": self.camera["id"],
            "status": self.status,
            "error": self.error,
            "resolution": self.resolution,
            "capture_fps": round(self.capture_fps, 1),
            "ai_fps": round(self.ai_fps, 1),
            "infer_ms": round(self.infer_ms, 1),
            **self.counts,
            "uptime_seconds": int(time.time() - self.started_at) if self.started_at and self.status != "stopped" else 0,
        }

    # ------------------------------------------------------------------ capture
    def _encode(self, img: np.ndarray, quality: int = 75) -> bytes:
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes() if ok else b""

    def _capture_loop(self) -> None:
        cam = self.camera
        cap = None
        backoff = 2.0
        fails = 0
        last_render = 0.0
        fps_count, fps_t = 0, time.time()
        is_file = cam["source_type"] == "file"
        file_fps = 25.0
        next_t = time.time()
        while not self._stop.is_set():
            if cap is None:
                self._set_status("connecting" if self.status in ("connecting", "stopped") else "reconnecting", self.error)
                try:
                    cap = open_source(cam["source_type"], cam["source"])
                except Exception as exc:  # noqa: BLE001
                    cap = None
                    self._set_status("error", str(exc))
                if cap is None or not cap.isOpened():
                    if cap is not None:
                        cap.release()
                    cap = None
                    self._set_status("reconnecting", f"Cannot open video source '{cam['source']}'. Retrying in {int(backoff)}s")
                    self.jpeg = self._encode(placeholder("NO SIGNAL", f"{cam['name']} - reconnecting..."))
                    self.jpeg_seq += 1
                    self._stop.wait(backoff)
                    backoff = min(backoff * 2, 20)
                    continue
                if is_file:
                    file_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
                    next_t = time.time()
                fails = 0
            ok, frame = cap.read()
            if not ok or frame is None:
                if is_file:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    fails += 1
                    if fails > 3:
                        cap.release()
                        cap = None
                    continue
                fails += 1
                if fails >= 25:
                    cap.release()
                    cap = None
                    self._set_status("reconnecting", "Video signal lost")
                else:
                    time.sleep(0.02)
                continue
            fails = 0
            backoff = 2.0
            if self.status != "online":
                self.resolution = f"{frame.shape[1]}x{frame.shape[0]}"
                self._set_status("online")
            if is_file:  # play video files in real time
                next_t += 1.0 / file_fps
                delay = next_t - time.time()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_t = time.time()
            with self._frame_lock:
                self._frame = frame
                self._frame_seq += 1
            self._new_frame.set()

            fps_count += 1
            now = time.time()
            if now - fps_t >= 1.0:
                self.capture_fps = fps_count / (now - fps_t)
                fps_count, fps_t = 0, now

            s = settings_store.get_settings()
            if now - last_render >= 1.0 / max(1, s["stream_fps"]):
                last_render = now
                items, ts = self._overlay
                view = frame.copy()
                if now - ts < 1.5:
                    draw_items(view, items)
                draw_hud(view, cam["name"], cam.get("location", ""), self.ai_fps, self.counts["persons"],
                         self.services.engine.ready)
                self.jpeg = self._encode(view, s["stream_jpeg_quality"])
                self.jpeg_seq += 1
        if cap is not None:
            cap.release()

    # ------------------------------------------------------------------ AI
    def _ai_loop(self) -> None:
        engine = self.services.engine
        last_seq = -1
        last_run = 0.0
        ai_count, ai_t = 0, time.time()
        last_pub = 0.0
        last_flush = time.time()
        while not self._stop.is_set():
            self._new_frame.wait(timeout=0.5)
            self._new_frame.clear()
            if self._stop.is_set():
                break
            if not engine.ready:
                time.sleep(0.2)
                continue
            s = settings_store.get_settings()
            min_gap = 1.0 / max(1, s["max_detection_fps"])
            wait = min_gap - (time.time() - last_run)
            if wait > 0:
                time.sleep(wait)
            with self._frame_lock:
                frame, seq = self._frame, self._frame_seq
            if frame is None or seq == last_seq:
                continue
            last_seq = seq
            last_run = time.time()
            try:
                self._process(frame, s)
            except Exception:  # noqa: BLE001
                log.exception("AI processing error on %s", self.camera["name"])
                time.sleep(0.5)
            ai_count += 1
            now = time.time()
            if now - ai_t >= 1.0:
                self.ai_fps = ai_count / (now - ai_t)
                ai_count, ai_t = 0, now
            if now - last_pub >= 1.0:
                last_pub = now
                bus.publish("camera_stats", self.snapshot())
            if now - last_flush >= 30:
                last_flush = now
                self._flush_stats()
                self.services.violations.expire(s)

    def _reid_loop(self) -> None:
        """Computes appearance embeddings in the background so detection never waits for Re-ID."""
        encoder = self.services.reid
        while not self._stop.is_set():
            try:
                frame, jobs, t_submit = self._reid_jobs.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                feats = encoder.embed(frame, np.array([j[1] for j in jobs], dtype=np.float32))
                with self._reid_lock:
                    for (tid, _box, clean, epoch), f in zip(jobs, feats):
                        self._reid_results[tid] = (f, t_submit, clean, epoch)
            except Exception:  # noqa: BLE001
                log.exception("Re-ID embedding failed on %s", self.camera["name"])
            finally:
                self._reid_inflight = set()

    def _get_tracker(self, s: dict) -> PersonTracker:
        key = (s["max_detection_fps"],)
        if self._tracker is None or key != self._tracker_key:
            self._tracker = PersonTracker(fps=float(s["max_detection_fps"]), buffer_seconds=3.0)
            self._tracker_key = key
        return self._tracker

    def _process(self, frame: np.ndarray, s: dict) -> None:
        svc = self.services
        engine, encoder, registry = svc.engine, svc.reid, svc.registry
        cam_id = self.camera["id"]
        required = [i for i in s["required_ppe"] if i in engine.supported_items]
        now = time.time()

        dets = engine.detect(frame, s)
        self.infer_ms = dets.infer_ms
        tracks = self._get_tracker(s).update(dets.person_xyxy, dets.person_conf)
        boxes = tracks[:, :4] if len(tracks) else np.zeros((0, 4), np.float32)
        observations = engine.associate(boxes, dets.ppe, required)

        # ---- update track states
        current: list[TrackInfo] = []
        for row, obs in zip(tracks, observations):
            tid = int(row[4])
            info = self.tracks.get(tid)
            if info is None:
                info = TrackInfo(tid, now, now, row[:4].copy())
                self.tracks[tid] = info
            info.box, info.last_t = row[:4].copy(), now
            info.ppe.update(obs, now, int(s["state_window"]), float(s["state_min_ratio"]))
            current.append(info)

        # ---- Re-ID: collect embeddings finished by the background Re-ID thread
        reid_on = bool(s.get("reid_enabled", True)) and encoder.ready
        results: dict[int, tuple] = {}
        if reid_on:
            with self._reid_lock:
                results, self._reid_results = self._reid_results, {}

        # ---- identity resolution / verification
        for info in current:
            res = results.get(info.track_id)
            if res is not None and res[3] != info.epoch:
                res = None  # result belongs to a previous identity of this track
            emb = res[0] if res is not None else None
            if info.worker is None:
                if emb is not None:
                    info.pending_embs.append(emb)
                age = now - info.first_t
                decide_emb = bool(info.pending_embs) and (len(info.pending_embs) >= 2 or age >= 2.0)
                no_emb_possible = age >= 4.0 and info.track_id not in self._reid_inflight
                if not reid_on or decide_emb or no_emb_possible:
                    mean = None
                    if info.pending_embs:
                        m = np.mean(info.pending_embs, axis=0)
                        mean = m / (np.linalg.norm(m) + 1e-12)
                    worker, matched, sim = registry.resolve(cam_id, info.track_id, mean, s)
                    info.worker = worker
                    info.pending_embs.clear()
                    info.last_verified_t = now if mean is not None else 0.0
                    if matched:
                        bus.publish("worker_reidentified", {"worker_code": worker.code, "camera_id": cam_id},
                                    activity=f"Worker {worker.code} re-identified on {self.camera['name']} "
                                             f"(similarity {sim:.2f})")
                    else:
                        bus.publish("worker_detected", {"worker_code": worker.code, "camera_id": cam_id},
                                    activity=f"New worker {worker.code} detected on {self.camera['name']}")
            else:
                # Appearance verification: ByteTrack associates boxes by position only, so a track can jump to a
                # different person (people crossing, abrupt scene changes). If the current appearance no longer
                # matches the worker profile twice in a row, the identity is dropped and resolved again.
                if emb is not None and info.worker.embedding is not None:
                    sim = float(np.dot(info.worker.embedding, emb))
                    if sim < float(s["reid_drift_threshold"]):
                        info.drift_count += 1
                        if info.drift_count >= 2:
                            log.info("Identity check failed for track %s (%s, similarity %.2f) - re-identifying",
                                     info.track_id, info.worker.code, sim)
                            registry.release(info.worker.worker_id, cam_id, info.track_id)
                            info.worker = None
                            info.pending_embs = [emb]
                            info.first_t = now
                            info.drift_count = 0
                            info.epoch += 1
                            info.ppe = TrackPPEState()
                        continue
                    info.drift_count = 0
                    info.last_verified_t = res[1]
                registry.update(info.worker.worker_id, cam_id, emb if (res is not None and res[2]) else None)

        # ---- Re-ID: submit crops that need an embedding (new identities, re-checks, periodic verification)
        if reid_on and current and not self._reid_inflight:
            overlap = _iou_max(boxes)
            jobs = []
            for k, info in enumerate(current):
                h = info.box[3] - info.box[1]
                if h < s["reid_min_crop_height"] or overlap[k] > 0.45:
                    continue  # too small or too occluded for a reliable appearance embedding
                due = info.worker is None or info.drift_count > 0 or now - info.last_emb_t >= 2.0
                if due:
                    jobs.append((info.track_id, info.box.copy(), bool(overlap[k] < 0.3), info.epoch))
                    info.last_emb_t = now
            if jobs:
                self._reid_inflight = {j[0] for j in jobs}
                try:
                    self._reid_jobs.put_nowait((frame, jobs, now))
                except queue.Full:
                    self._reid_inflight = set()

        # ---- violations
        min_secs = float(s["violation_min_seconds"])
        overlay = self._build_overlay(current, observations, required)
        for info in current:
            if info.worker is None or info.drift_count > 0:
                continue
            for item in required:
                st = info.ppe.items.get(item)
                if not (st and st.state == "MISSING" and st.missing_since is not None
                        and now - st.missing_since >= min_secs):
                    continue
                # the identity must have been confirmed by appearance after the violation started
                # (unless no appearance check was possible, e.g. a small / occluded person)
                if reid_on and info.last_verified_t < st.missing_since and (
                        info.last_emb_t >= st.missing_since or info.track_id in self._reid_inflight):
                    continue
                tid = info.track_id
                svc.violations.report(
                    worker_id=info.worker.worker_id, worker_code=info.worker.code, item=item,
                    confidence=st.conf, camera=self.camera, frame=frame, settings=s,
                    render_evidence=lambda f, banner, _t=tid: render_evidence(f, overlay, _t, banner),
                )

        # ---- drop stale tracks
        for tid in [t for t, i in self.tracks.items() if now - i.last_t > 4.0]:
            info = self.tracks.pop(tid)
            if info.worker:
                registry.release(info.worker.worker_id, cam_id, tid)

        # ---- stats
        statuses = [it.status for it in overlay]
        self.counts = {"persons": len(current), "compliant": statuses.count("COMPLIANT"),
                       "violations": statuses.count("VIOLATION"), "unknown": statuses.count("UNKNOWN")}
        st = self._stats
        st["frames"] += 1
        st["persons"] += len(current)
        st["compliant"] += self.counts["compliant"]
        st["violation"] += self.counts["violations"]
        st["unknown"] += self.counts["unknown"]
        self._overlay = (overlay, time.time())

    def _build_overlay(self, current: list[TrackInfo], observations, required: list[str]) -> list[OverlayItem]:
        items = []
        for info, obs in zip(current, observations):
            status = info.ppe.overall(required)
            title = info.worker.code if info.worker else "Identifying..."
            states = {i: info.ppe.items.get(i) for i in required}
            missing = [i for i in required if states[i] and states[i].state == "MISSING"]
            lines: list[str] = []
            if status == "VIOLATION":
                lines = [f"{LIVE_TEXT.get(i, i.upper())} {round(states[i].conf * 100)}%" for i in missing]
            elif status == "COMPLIANT":
                lines = ["PPE COMPLIANT",
                         "  ".join(f"{ITEM_NAMES.get(i, i)} {round(states[i].conf * 100)}%" for i in required)]
            else:
                parts = []
                for i in required:
                    stt = states[i]
                    if stt and stt.state == "PRESENT":
                        parts.append(f"{ITEM_NAMES.get(i, i)}: OK {round(stt.conf * 100)}%")
                    else:
                        parts.append(f"{ITEM_NAMES.get(i, i)}: ?")
                lines = ["PPE UNKNOWN", "  ".join(parts)]
            gear = []
            for item, o in obs.items():
                if o.box is None:
                    continue
                g = tuple(int(v) for v in o.box)
                if o.state == "PRESENT":
                    gear.append((g, GREEN, f"{ITEM_NAMES.get(item, item)} {round(o.conf * 100)}%"))
                elif o.state == "MISSING":
                    gear.append((g, RED, f"No {ITEM_NAMES.get(item, item).lower()} {round(o.conf * 100)}%"))
            x1, y1, x2, y2 = (int(v) for v in info.box)
            items.append(OverlayItem((x1, y1, x2, y2), status, title, lines, gear, info.track_id))
        return items

    def _flush_stats(self) -> None:
        st = self._stats
        if not st["frames"]:
            return
        hour = datetime.now().replace(minute=0, second=0, microsecond=0)
        try:
            with session_scope() as s:
                row = s.query(DetectionStat).filter_by(camera_id=self.camera["id"], hour=hour).first()
                if row is None:
                    row = DetectionStat(camera_id=self.camera["id"], hour=hour, frames_processed=0,
                                        person_detections=0, compliant_observations=0,
                                        violation_observations=0, unknown_observations=0)
                    s.add(row)
                row.frames_processed += st["frames"]
                row.person_detections += st["persons"]
                row.compliant_observations += st["compliant"]
                row.violation_observations += st["violation"]
                row.unknown_observations += st["unknown"]
            self._stats = {k: 0 for k in st}
        except Exception:  # noqa: BLE001
            log.exception("Failed to store detection stats")
