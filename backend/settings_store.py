"""Thread-safe runtime settings backed by the ``app_settings`` table."""
from __future__ import annotations

import copy
import threading

from backend.config import DEFAULT_SETTINGS, SECRET_SETTINGS
from backend.database.db import session_scope
from backend.database.models import AppSetting

_lock = threading.RLock()
_cache: dict | None = None

# Allowed ranges for numeric settings: key -> (min, max)
_RANGES = {
    "person_confidence": (0.05, 0.99),
    "ppe_present_confidence": (0.05, 0.99),
    "ppe_missing_confidence": (0.05, 0.99),
    "inference_size": (320, 1280),
    "max_detection_fps": (1, 30),
    "state_window": (1, 60),
    "state_min_ratio": (0.3, 1.0),
    "violation_min_seconds": (0.0, 60.0),
    "duplicate_window_seconds": (0, 86400),
    "notification_cooldown_seconds": (0, 86400),
    "reid_similarity_threshold": (0.3, 0.99),
    "reid_margin": (0.0, 0.5),
    "reid_drift_threshold": (0.0, 0.9),
    "reid_memory_minutes": (1, 1440),
    "reid_min_crop_height": (32, 1000),
    "evidence_jpeg_quality": (30, 100),
    "stream_fps": (1, 30),
    "stream_jpeg_quality": (30, 95),
}


def _load() -> dict:
    data = copy.deepcopy(DEFAULT_SETTINGS)
    with session_scope() as s:
        for row in s.query(AppSetting).all():
            if row.key in data:
                data[row.key] = row.value
    return data


def get_settings() -> dict:
    global _cache
    with _lock:
        if _cache is None:
            _cache = _load()
        return copy.deepcopy(_cache)


def get(key: str):
    with _lock:
        if _cache is None:
            get_settings()
        return copy.deepcopy(_cache[key])  # type: ignore[index]


def _coerce(key: str, value):
    default = DEFAULT_SETTINGS[key]
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(default, int) and not isinstance(default, bool):
        value = int(float(value))
    elif isinstance(default, float):
        value = float(value)
    elif isinstance(default, list):
        if not isinstance(value, list):
            raise ValueError(f"{key} must be a list")
        if key == "required_ppe":
            allowed = {"helmet", "vest"}
            value = [v for v in value if v in allowed]
    elif isinstance(default, str):
        value = str(value).strip()
        if key == "person_detector" and value not in ("coco", "ppe"):
            raise ValueError("person_detector must be 'coco' or 'ppe'")
    if key in _RANGES:
        lo, hi = _RANGES[key]
        if not (lo <= value <= hi):
            raise ValueError(f"{key} must be between {lo} and {hi}")
    return value


def update_settings(changes: dict) -> dict:
    global _cache
    clean = {}
    for key, value in changes.items():
        if key not in DEFAULT_SETTINGS:
            continue
        if key in SECRET_SETTINGS and (value is None or "****" in str(value)):
            continue  # masked value sent back unchanged -> keep the stored secret
        clean[key] = _coerce(key, value)
    with _lock:
        with session_scope() as s:
            for key, value in clean.items():
                row = s.get(AppSetting, key)
                if row is None:
                    s.add(AppSetting(key=key, value=value))
                else:
                    row.value = value
        _cache = None
        return get_settings()


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


def public_settings() -> dict:
    data = get_settings()
    for key in SECRET_SETTINGS:
        data[key + "_set"] = bool(data.get(key))
        data[key] = mask_secret(data.get(key, ""))
    return data
