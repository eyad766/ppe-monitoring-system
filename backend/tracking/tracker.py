"""ByteTrack multi-object tracker (Ultralytics implementation) for person boxes."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from backend.detection.ppe_detector import TrackerInput


class PersonTracker:
    def __init__(self, fps: float = 8.0, buffer_seconds: float = 3.0):
        from ultralytics.trackers.byte_tracker import BYTETracker

        args = SimpleNamespace(
            tracker_type="bytetrack",
            track_high_thresh=0.45,
            track_low_thresh=0.15,
            new_track_thresh=0.5,
            track_buffer=max(5, int(round(fps * buffer_seconds))),
            match_thresh=0.8,
            fuse_score=True,
        )
        self._tracker = BYTETracker(args)

    def update(self, xyxy: np.ndarray, conf: np.ndarray) -> np.ndarray:
        """Returns rows of [x1, y1, x2, y2, track_id, score, cls, det_idx]."""
        out = self._tracker.update(TrackerInput(xyxy, conf))
        if out is None or len(out) == 0:
            return np.zeros((0, 8), dtype=np.float32)
        return np.asarray(out, dtype=np.float32)
