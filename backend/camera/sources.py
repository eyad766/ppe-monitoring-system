"""Video source helpers: local webcam discovery (incl. Iriun Webcam) and capture opening."""
from __future__ import annotations

import logging
import os
import platform

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_OBSENSOR", "0")

import cv2  # noqa: E402

try:  # silence OpenCV's console noise while probing camera indexes
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
except Exception:  # noqa: BLE001
    pass

log = logging.getLogger("camera.sources")
IS_WINDOWS = platform.system() == "Windows"

# Prefer TCP for RTSP (more reliable over Wi-Fi / NAT) and a 10 s socket timeout.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;10000000")


def _device_names() -> list[str]:
    """DirectShow device names in index order (Windows). Empty list when unavailable."""
    if not IS_WINDOWS:
        return []
    try:
        from pygrabber.dshow_graph import FilterGraph

        return list(FilterGraph().get_input_devices())
    except Exception as exc:  # noqa: BLE001
        log.debug("pygrabber unavailable: %s", exc)
        return []


def list_webcams(max_index: int = 6, busy: set[int] | None = None, probe: bool = True) -> list[dict]:
    busy = busy or set()
    names = _device_names()
    count = len(names) if names else max_index
    result = []
    for idx in range(count):
        name = names[idx] if idx < len(names) else f"Camera device {idx}"
        entry = {"index": idx, "name": name, "available": None, "resolution": None,
                 "is_iriun": "iriun" in name.lower()}
        if idx in busy:
            entry.update(available=True, in_use=True)
        elif probe:
            cap = open_webcam(idx, set_resolution=False)
            ok = cap.isOpened()
            if ok:
                ok, frame = cap.read()
                if ok and frame is not None:
                    entry["resolution"] = f"{frame.shape[1]}x{frame.shape[0]}"
            cap.release()
            entry["available"] = bool(ok)
            if not names and not ok:
                continue  # unnamed index with no device -> skip
        result.append(entry)
    return result


def open_webcam(index: int, set_resolution: bool = True, width: int = 1280, height: int = 720) -> cv2.VideoCapture:
    backend = cv2.CAP_DSHOW if IS_WINDOWS else cv2.CAP_ANY
    cap = cv2.VideoCapture(int(index), backend)
    if not cap.isOpened() and IS_WINDOWS:
        cap = cv2.VideoCapture(int(index), cv2.CAP_MSMF)
    if cap.isOpened() and set_resolution:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def open_source(source_type: str, source: str) -> cv2.VideoCapture:
    if source_type == "webcam":
        return open_webcam(int(source))
    if source_type in ("rtsp", "http"):
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap
    if source_type == "file":
        return cv2.VideoCapture(source)
    raise ValueError(f"Unknown source type: {source_type}")
