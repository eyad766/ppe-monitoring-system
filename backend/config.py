"""Application paths, static configuration and default runtime settings.

Runtime-editable settings (thresholds, de-duplication rules, Telegram) are stored in
the database (table ``app_settings``) and fall back to the defaults defined here.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")

BACKEND_DIR = ROOT_DIR / "backend"
MODELS_DIR = ROOT_DIR / "models"
DATA_DIR = ROOT_DIR / "data"
VIOLATIONS_DIR = DATA_DIR / "violations"
REPORTS_DIR = ROOT_DIR / "reports"
LOGS_DIR = ROOT_DIR / "logs"
CONFIG_DIR = ROOT_DIR / "config"
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"

for _d in (MODELS_DIR, DATA_DIR, VIOLATIONS_DIR, REPORTS_DIR, LOGS_DIR, CONFIG_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


APP_NAME = "SiteGuard AI - PPE Monitoring System"
APP_VERSION = "1.0.0 (Phase 1)"
HOST = _env("APP_HOST", "127.0.0.1")
PORT = int(_env("APP_PORT", "8000"))
OPEN_BROWSER = _env("OPEN_BROWSER", "1") == "1"
DATABASE_URL = _env("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'monitoring.db').as_posix()}")

PPE_MODEL_PATH = Path(_env("PPE_MODEL_PATH", str(MODELS_DIR / "ppe_yolov8n.pt")))
PERSON_MODEL_PATH = Path(_env("PERSON_MODEL_PATH", str(MODELS_DIR / "person_yolov8n_coco.pt")))
REID_MODEL_PATH = Path(_env("REID_MODEL_PATH", str(MODELS_DIR / "reid_lmbn_n_market.onnx")))
# "auto" uses CUDA when available, otherwise CPU. Can be set to "cpu" or "0" (first GPU).
INFERENCE_DEVICE = _env("INFERENCE_DEVICE", "auto")

# Default runtime settings. Every key here can be changed from the Settings page.
DEFAULT_SETTINGS: dict = {
    # --- Detection ---
    "required_ppe": ["helmet", "vest"],      # PPE items that must be worn
    "person_detector": "coco",                # "coco" (dedicated person model) or "ppe" (PPE model Person class)
    "person_confidence": 0.45,                # minimum confidence to accept a person detection
    "ppe_present_confidence": 0.45,           # minimum confidence for Hardhat / Safety Vest
    "ppe_missing_confidence": 0.50,           # minimum confidence for NO-Hardhat / NO-Safety Vest
    "inference_size": 640,                    # YOLO input size (pixels)
    "max_detection_fps": 8,                   # upper limit of AI inferences per second per camera
    # --- Temporal decision (anti-flicker) ---
    "state_window": 8,                        # number of recent AI frames used to decide each PPE state
    "state_min_ratio": 0.6,                   # share of the window that must agree for MISSING / PRESENT
    "violation_min_seconds": 2.0,             # a missing item must persist this long before a violation is registered
    # --- Duplicate prevention ---
    "duplicate_window_seconds": 300,          # same worker + same violation within this window = same incident
    "notification_cooldown_seconds": 300,     # minimum time between alerts for the same worker + violation type
    # --- Re-identification ---
    "reid_enabled": True,
    "reid_similarity_threshold": 0.72,        # cosine similarity needed to match a previously seen worker
    "reid_margin": 0.06,                      # best match must beat the 2nd best by this margin (prevents wrong merges)
    "reid_drift_threshold": 0.45,             # below this, a tracked box no longer looks like its worker -> re-identify
    "reid_memory_minutes": 30,                # how long a worker's appearance is remembered
    "reid_min_crop_height": 96,               # crops smaller than this (pixels) are not used for Re-ID
    # --- Evidence / stream ---
    "evidence_jpeg_quality": 90,
    "stream_fps": 15,
    "stream_jpeg_quality": 75,
    # --- Telegram ---
    "telegram_enabled": False,
    "telegram_bot_token": _env("TELEGRAM_BOT_TOKEN", ""),
    "telegram_chat_id": _env("TELEGRAM_CHAT_ID", ""),
    "telegram_send_photo": True,
}

SECRET_SETTINGS = {"telegram_bot_token"}

VIOLATION_TYPES = {
    "helmet": "Missing Safety Helmet",
    "vest": "Missing Safety Vest",
}
VIOLATION_STATUSES = ["Open", "Under Review", "Closed"]
