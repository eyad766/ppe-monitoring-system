r"""Download the AI model files into the models folder (run automatically by install.bat).

    .venv\Scripts\python.exe tools\download_models.py [--force]

Sources
* PPE model   : YOLOv8n trained on the Roboflow "Construction Site Safety" dataset (Hardhat, NO-Hardhat,
                Safety Vest, NO-Safety Vest, Person, ...) - github.com/snehilsanyal/Construction-Site-Safety-PPE-Detection
* Person model: YOLOv8n COCO (Ultralytics)
* Re-ID model : LMBN-n trained on Market-1501 (BoxMOT model zoo), exported to ONNX with tools/export_reid_onnx.py.
                Included in the repository as models/reid_lmbn_n_market.onnx.part0/.part1 (joined automatically).
"""
import sys
import urllib.request
from pathlib import Path

MODELS = Path(__file__).resolve().parents[1] / "models"
FILES = {
    "ppe_yolov8n.pt": [
        "https://github.com/snehilsanyal/Construction-Site-Safety-PPE-Detection/raw/main/models/best.pt",
        "https://raw.githubusercontent.com/snehilsanyal/Construction-Site-Safety-PPE-Detection/main/models/best.pt",
    ],
    "person_yolov8n_coco.pt": [
        "https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8n.pt",
    ],
}
REID_SOURCE = "https://github.com/mikel-brostrom/boxmot/releases/download/v21.0.0/lmbn_n_market.pt"


def download(url: str, dst: Path) -> None:
    tmp = dst.with_suffix(".download")
    req = urllib.request.Request(url, headers={"User-Agent": "ppe-monitoring-system"})
    with urllib.request.urlopen(req, timeout=180) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(dst)


def main() -> int:
    MODELS.mkdir(exist_ok=True)
    force = "--force" in sys.argv
    failed = False
    for name, urls in FILES.items():
        dst = MODELS / name
        if dst.exists() and dst.stat().st_size > 1_000_000 and not force:
            print(f"[OK] {name} already present")
            continue
        for url in urls:
            print(f"[..] Downloading {name}")
            try:
                download(url, dst)
                print(f"[OK] {name} ({dst.stat().st_size / 1e6:.1f} MB)")
                break
            except Exception as exc:  # noqa: BLE001
                print(f"[!] {url} failed: {exc}")
        else:
            failed = True
            print(f"[X] Could not download {name}")
    if not (MODELS / "reid_lmbn_n_market.onnx").exists() and not any(MODELS.glob("reid_lmbn_n_market.onnx.part*")):
        print("[!] The Re-ID model is missing. Recreate it with tools/export_reid_onnx.py "
              f"(weights: {REID_SOURCE}). The system still runs without cross-camera Re-ID.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
