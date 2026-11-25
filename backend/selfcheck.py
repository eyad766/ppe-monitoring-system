"""Environment self-check:  python -m backend.selfcheck   (or check.bat)

Verifies Python, packages, AI models (real inference on a test image) and lists the cameras
that Windows exposes (e.g. "Iriun Webcam").
"""
from __future__ import annotations

import importlib
import platform
import sys
import time

OK, WARN, FAIL = "[ OK ]", "[WARN]", "[FAIL]"
problems = 0


def line(tag, msg):
    global problems
    if tag == FAIL:
        problems += 1
    print(f"{tag} {msg}", flush=True)


def main() -> int:
    print("=" * 70)
    print(" PPE Monitoring System - environment check")
    print("=" * 70)
    v = sys.version_info
    line(OK if (3, 9) <= v[:2] <= (3, 13) else WARN, f"Python {platform.python_version()} ({platform.architecture()[0]}) on {platform.system()} {platform.release()}")

    for mod, name in [("cv2", "OpenCV"), ("torch", "PyTorch"), ("ultralytics", "Ultralytics YOLO"), ("onnxruntime", "ONNX Runtime"),
                      ("fastapi", "FastAPI"), ("uvicorn", "Uvicorn"), ("sqlalchemy", "SQLAlchemy"), ("lap", "lap (ByteTrack)"),
                      ("httpx", "httpx")]:
        try:
            m = importlib.import_module(mod)
            line(OK, f"{name} {getattr(m, '__version__', '')}")
        except Exception as exc:  # noqa: BLE001
            line(FAIL, f"{name} not installed ({exc}) - run install.bat")
    if platform.system() == "Windows":
        try:
            importlib.import_module("pygrabber")
            line(OK, "pygrabber (camera names)")
        except Exception:  # noqa: BLE001
            line(WARN, "pygrabber missing - cameras will be listed by number only")

    try:
        import torch

        if torch.cuda.is_available():
            line(OK, f"GPU: {torch.cuda.get_device_name(0)} (CUDA)")
        else:
            line(OK, "Inference device: CPU (no CUDA GPU build of PyTorch detected)")
    except Exception:  # noqa: BLE001
        pass

    if problems:
        print("\nFix the package problems above, then run this check again.")
        return 1

    import numpy as np

    from backend.config import PERSON_MODEL_PATH, PPE_MODEL_PATH, REID_MODEL_PATH, DEFAULT_SETTINGS
    from backend.detection.ppe_detector import PPEDetectionEngine
    from backend.tracking.reid import ReIDEncoder

    for p in (PPE_MODEL_PATH, PERSON_MODEL_PATH, REID_MODEL_PATH):
        found = p.exists() or any(p.parent.glob(p.name + ".part*"))
        line(OK if found else FAIL, f"Model file {p.name} {'found' if found else 'MISSING'}")
    eng = PPEDetectionEngine(PPE_MODEL_PATH, PERSON_MODEL_PATH, "auto")
    eng.load()
    if eng.ready:
        line(OK, f"PPE model loaded - classes: {', '.join(eng.ppe_model.names.values())}")
        img = np.random.default_rng(0).integers(0, 255, (720, 1280, 3), dtype=np.uint8)
        t = time.perf_counter()
        for _ in range(3):
            eng.detect(img, DEFAULT_SETTINGS)
        ms = (time.perf_counter() - t) / 3 * 1000
        line(OK if ms < 400 else WARN, f"AI speed: {ms:.0f} ms per frame (~{1000 / ms:.1f} AI frames/s per camera)")
    else:
        line(FAIL, f"AI engine failed: {eng.error}")
    reid = ReIDEncoder(REID_MODEL_PATH)
    reid.load()
    if reid.ready:
        t = time.perf_counter()
        reid.embed(np.zeros((720, 1280, 3), np.uint8), np.array([[100, 100, 300, 600]], np.float32))
        line(OK, f"Re-ID model loaded ({(time.perf_counter() - t) * 1000:.0f} ms per person)")
    else:
        line(WARN, f"Re-ID unavailable: {reid.error}")

    print("\nCameras visible to Windows:")
    from backend.camera.sources import list_webcams

    cams = list_webcams(max_index=6)
    if not cams:
        line(WARN, "No camera found. Start Iriun Webcam on the PC and on the phone (same Wi-Fi), then retry.")
    for c in cams:
        tag = OK if c["available"] else WARN
        line(tag, f"  [{c['index']}] {c['name']} - {'working, ' + c['resolution'] if c['available'] else 'no image'}"
                  f"{'   <-- Iriun Webcam' if c['is_iriun'] else ''}")
    print("\n" + ("All checks passed." if not problems else f"{problems} problem(s) found."))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
