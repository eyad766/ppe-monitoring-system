"""Per-track temporal smoothing of PPE observations (prevents flicker and one-frame false alarms)."""
from __future__ import annotations

import collections
from dataclasses import dataclass, field

from backend.detection.ppe_detector import ItemObservation


@dataclass
class ItemState:
    state: str = "UNKNOWN"  # PRESENT | MISSING | UNKNOWN
    conf: float = 0.0
    missing_since: float | None = None
    history: collections.deque = field(default_factory=lambda: collections.deque(maxlen=60))


class TrackPPEState:
    def __init__(self):
        self.items: dict[str, ItemState] = {}

    def update(self, observations: dict[str, ItemObservation], now: float, window: int, min_ratio: float) -> None:
        for item, obs in observations.items():
            st = self.items.setdefault(item, ItemState())
            st.history.append((obs.state, obs.conf))
            recent = list(st.history)[-window:]
            n = len(recent)
            missing = [c for s, c in recent if s == "MISSING"]
            present = [c for s, c in recent if s == "PRESENT"]
            min_obs = min(3, window)
            if n >= min_obs and len(missing) / n >= min_ratio:
                st.state, st.conf = "MISSING", sum(missing) / len(missing)
            elif n >= min_obs and len(present) / n >= min_ratio:
                st.state, st.conf = "PRESENT", sum(present) / len(present)
            elif st.state in ("MISSING", "PRESENT") and n >= min_obs:
                # hysteresis: keep the previous decided state while evidence is mixed,
                # unless the opposite evidence is now the majority
                same = missing if st.state == "MISSING" else present
                opposite = present if st.state == "MISSING" else missing
                if len(opposite) > len(same) or len(same) / n < 0.34:
                    st.state, st.conf = "UNKNOWN", 0.0
            else:
                st.state, st.conf = "UNKNOWN", 0.0
            if st.state == "MISSING":
                if st.missing_since is None:
                    st.missing_since = now
            else:
                st.missing_since = None

    def overall(self, required: list[str]) -> str:
        states = [self.items.get(i, ItemState()).state for i in required]
        if not states:
            return "UNKNOWN"
        if "MISSING" in states:
            return "VIOLATION"
        if all(s == "PRESENT" for s in states):
            return "COMPLIANT"
        return "UNKNOWN"
