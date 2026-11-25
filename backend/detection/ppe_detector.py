"""AI detection engine.

* Person detection: dedicated COCO-trained YOLOv8 person detector (or the PPE model's own
  ``Person`` class, selectable in Settings).
* PPE detection: YOLOv8 model trained on construction-site PPE data with positive AND negative
  classes (``Hardhat`` / ``NO-Hardhat``, ``Safety Vest`` / ``NO-Safety Vest``). A violation is only
  possible when the model positively detects the *absence* of an item (a NO-* class) - the system
  never infers "no helmet" from "no helmet box found"; that case is reported as UNKNOWN.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

log = logging.getLogger("detection")

# PPE model class-name aliases -> (item, polarity). Lets other PPE models be dropped in later.
CLASS_ALIASES: dict[str, tuple[str, str]] = {
    "hardhat": ("helmet", "present"),
    "helmet": ("helmet", "present"),
    "safety helmet": ("helmet", "present"),
    "no-hardhat": ("helmet", "missing"),
    "no_hardhat": ("helmet", "missing"),
    "no-helmet": ("helmet", "missing"),
    "no_helmet": ("helmet", "missing"),
    "head": ("helmet", "missing"),
    "safety vest": ("vest", "present"),
    "safety-vest": ("vest", "present"),
    "vest": ("vest", "present"),
    "no-safety vest": ("vest", "missing"),
    "no-safety-vest": ("vest", "missing"),
    "no_vest": ("vest", "missing"),
    "no-vest": ("vest", "missing"),
    "shoes": ("shoes", "present"),
    "safety shoes": ("shoes", "present"),
    "boots": ("shoes", "present"),
    "no_shoes": ("shoes", "missing"),
    "no-shoes": ("shoes", "missing"),
}

# Vertical band of the person box (fraction of height, from the top) in which each item is expected.
ITEM_REGIONS = {
    "helmet": (-0.15, 0.55),
    "vest": (0.10, 0.95),
    "shoes": (0.60, 1.10),
}

PERSON_CLASS_NAMES = {"person", "worker"}


@dataclass
class PPEBox:
    item: str
    polarity: str  # present | missing
    xyxy: np.ndarray
    conf: float
    class_name: str


@dataclass
class FrameDetections:
    person_xyxy: np.ndarray  # (N, 4)
    person_conf: np.ndarray  # (N,)
    ppe: list[PPEBox] = field(default_factory=list)
    infer_ms: float = 0.0


@dataclass
class ItemObservation:
    state: str  # PRESENT | MISSING | UNKNOWN
    conf: float = 0.0
    box: np.ndarray | None = None


class TrackerInput:
    """Minimal NumPy container matching the interface ByteTrack expects (conf, cls, xywh, bool indexing)."""

    def __init__(self, xyxy: np.ndarray, conf: np.ndarray):
        self.xyxy = xyxy.astype(np.float32).reshape(-1, 4)
        self.conf = conf.astype(np.float32).reshape(-1)
        self.cls = np.zeros_like(self.conf)
        xywh = self.xyxy.copy()
        xywh[:, 2] = self.xyxy[:, 2] - self.xyxy[:, 0]
        xywh[:, 3] = self.xyxy[:, 3] - self.xyxy[:, 1]
        xywh[:, 0] = self.xyxy[:, 0] + xywh[:, 2] / 2
        xywh[:, 1] = self.xyxy[:, 1] + xywh[:, 3] / 2
        self.xywh = xywh

    def __len__(self) -> int:
        return len(self.conf)

    def __getitem__(self, idx) -> "TrackerInput":
        return TrackerInput(self.xyxy[idx], self.conf[idx])


class PPEDetectionEngine:
    def __init__(self, ppe_model_path: Path, person_model_path: Path, device: str = "auto"):
        self.ppe_model_path = Path(ppe_model_path)
        self.person_model_path = Path(person_model_path)
        self.requested_device = device
        self.device = "cpu"
        self.ppe_model = None
        self.person_model = None
        self.class_map: dict[int, tuple[str, str]] = {}
        self.ppe_person_class_ids: list[int] = []
        self.supported_items: set[str] = set()
        self.ready = False
        self.error: str | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ loading
    def load(self) -> None:
        try:
            import torch
            from ultralytics import YOLO

            if self.requested_device == "auto":
                self.device = "0" if torch.cuda.is_available() else "cpu"
            else:
                self.device = self.requested_device

            if not self.ppe_model_path.exists():
                raise FileNotFoundError(f"PPE model not found: {self.ppe_model_path}")
            self.ppe_model = YOLO(str(self.ppe_model_path))
            names = self.ppe_model.names
            for cid, name in names.items():
                key = str(name).strip().lower()
                if key in CLASS_ALIASES:
                    self.class_map[int(cid)] = CLASS_ALIASES[key]
                    self.supported_items.add(CLASS_ALIASES[key][0])
                elif key in PERSON_CLASS_NAMES:
                    self.ppe_person_class_ids.append(int(cid))
            if "helmet" not in self.supported_items:
                raise ValueError(
                    f"The PPE model {self.ppe_model_path.name} has no helmet classes ({list(names.values())}). "
                    "A real PPE detection model is required."
                )
            for item in self.supported_items:
                pols = {p for (i, p) in self.class_map.values() if i == item}
                if "missing" not in pols:
                    log.warning("PPE model has no 'missing' class for %s - violations for it cannot be confirmed", item)

            if self.person_model_path.exists():
                self.person_model = YOLO(str(self.person_model_path))
                pnames = {str(v).lower() for v in self.person_model.names.values()}
                if "person" not in pnames:
                    log.warning("Person model has no 'person' class; falling back to PPE model persons")
                    self.person_model = None
            else:
                log.warning("Person model not found (%s); using the PPE model's Person class", self.person_model_path)

            # warm-up
            dummy = np.zeros((480, 640, 3), dtype=np.uint8)
            self.detect(dummy, {"person_detector": "coco", "person_confidence": 0.5,
                                "ppe_present_confidence": 0.5, "ppe_missing_confidence": 0.5,
                                "inference_size": 640})
            self.ready = True
            log.info("AI engine ready | device=%s | PPE classes=%s | items=%s | person model=%s",
                     self.device, list(names.values()), sorted(self.supported_items),
                     self.person_model_path.name if self.person_model else "PPE model")
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            self.ready = False
            log.exception("Failed to load AI models")

    def info(self) -> dict:
        return {
            "ready": self.ready,
            "error": self.error,
            "device": "GPU (CUDA)" if self.device not in ("cpu",) else "CPU",
            "ppe_model": self.ppe_model_path.name,
            "ppe_classes": list(self.ppe_model.names.values()) if self.ppe_model else [],
            "supported_items": sorted(self.supported_items),
            "person_model": self.person_model_path.name if self.person_model else None,
        }

    # ------------------------------------------------------------------ inference
    def detect(self, frame: np.ndarray, settings: dict) -> FrameDetections:
        imgsz = int(settings.get("inference_size", 640))
        p_conf = float(settings.get("person_confidence", 0.45))
        min_ppe = min(float(settings.get("ppe_present_confidence", 0.45)),
                      float(settings.get("ppe_missing_confidence", 0.5)))
        use_coco = settings.get("person_detector", "coco") == "coco" and self.person_model is not None
        t0 = time.perf_counter()
        with self._lock:
            ppe_res = self.ppe_model.predict(frame, conf=min(min_ppe, p_conf) * 0.9, imgsz=imgsz,
                                             device=self.device, verbose=False)[0]
            if use_coco:
                pres = self.person_model.predict(frame, conf=p_conf * 0.6, imgsz=imgsz, classes=[0],
                                                 device=self.device, verbose=False)[0]
        infer_ms = (time.perf_counter() - t0) * 1000

        b = ppe_res.boxes
        xyxy = b.xyxy.cpu().numpy() if len(b) else np.zeros((0, 4), np.float32)
        conf = b.conf.cpu().numpy() if len(b) else np.zeros((0,), np.float32)
        cls = b.cls.cpu().numpy().astype(int) if len(b) else np.zeros((0,), int)

        ppe: list[PPEBox] = []
        for box, c, k in zip(xyxy, conf, cls):
            if k in self.class_map:
                item, pol = self.class_map[k]
                th = settings.get("ppe_present_confidence", 0.45) if pol == "present" else settings.get("ppe_missing_confidence", 0.5)
                if c >= float(th):
                    ppe.append(PPEBox(item, pol, box, float(c), self.ppe_model.names[k]))

        if use_coco:
            pb = pres.boxes
            p_xyxy = pb.xyxy.cpu().numpy() if len(pb) else np.zeros((0, 4), np.float32)
            p_cf = pb.conf.cpu().numpy() if len(pb) else np.zeros((0,), np.float32)
        else:
            mask = np.isin(cls, self.ppe_person_class_ids)
            p_xyxy, p_cf = xyxy[mask], conf[mask]
        return FrameDetections(p_xyxy.reshape(-1, 4), p_cf.reshape(-1), ppe, infer_ms)

    # ------------------------------------------------------------------ association
    @staticmethod
    def associate(person_boxes: np.ndarray, ppe: list[PPEBox], items: list[str]) -> list[dict[str, ItemObservation]]:
        """Assign every PPE box to at most one person, then decide PRESENT / MISSING / UNKNOWN per item."""
        n = len(person_boxes)
        assigned: list[list[PPEBox]] = [[] for _ in range(n)]
        for g in ppe:
            gx1, gy1, gx2, gy2 = g.xyxy
            gcx, gcy = (gx1 + gx2) / 2, (gy1 + gy2) / 2
            garea = max((gx2 - gx1) * (gy2 - gy1), 1.0)
            lo, hi = ITEM_REGIONS.get(g.item, (0.0, 1.0))
            best, best_score = -1, 0.0
            for i, (x1, y1, x2, y2) in enumerate(person_boxes):
                w, h = x2 - x1, y2 - y1
                if w <= 1 or h <= 1:
                    continue
                if not (x1 - 0.1 * w <= gcx <= x2 + 0.1 * w):
                    continue
                if not (y1 + lo * h <= gcy <= y1 + hi * h):
                    continue
                ix = max(0.0, min(gx2, x2 + 0.1 * w) - max(gx1, x1 - 0.1 * w))
                iy = max(0.0, min(gy2, y2) - max(gy1, y1 - 0.15 * h))
                ioa = ix * iy / garea
                if ioa < 0.4:
                    continue
                # prefer the person whose horizontal centre is closest (crowded scenes)
                score = ioa - abs(gcx - (x1 + x2) / 2) / max(w, 1.0) * 0.5
                if score > best_score:
                    best, best_score = i, score
            if best >= 0:
                assigned[best].append(g)

        out: list[dict[str, ItemObservation]] = []
        for gear in assigned:
            obs: dict[str, ItemObservation] = {}
            for item in items:
                pos = [g for g in gear if g.item == item and g.polarity == "present"]
                neg = [g for g in gear if g.item == item and g.polarity == "missing"]
                bp = max(pos, key=lambda g: g.conf) if pos else None
                bn = max(neg, key=lambda g: g.conf) if neg else None
                if bp and (not bn or bp.conf >= bn.conf):
                    obs[item] = ItemObservation("PRESENT", bp.conf, bp.xyxy)
                elif bn:
                    obs[item] = ItemObservation("MISSING", bn.conf, bn.xyxy)
                else:
                    obs[item] = ItemObservation("UNKNOWN")
            out.append(obs)
        return out
