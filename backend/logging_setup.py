import logging
from logging.handlers import RotatingFileHandler

from backend.config import LOGS_DIR


def setup_logging(level: int = logging.INFO) -> None:
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    if getattr(root, "_ppe_configured", False):
        return
    root.setLevel(level)
    file_handler = RotatingFileHandler(LOGS_DIR / "app.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(file_handler)
    root.addHandler(console)
    for noisy in ("uvicorn.access", "httpx", "ultralytics"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    root._ppe_configured = True  # type: ignore[attr-defined]
