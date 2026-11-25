# SiteGuard AI – PPE Monitoring System

AI-powered Personal Protective Equipment (PPE) monitoring for construction sites. The system reads CCTV / IP / USB cameras, detects workers who are **not wearing a safety helmet or safety vest**, tracks each worker with a temporary Worker ID, records every violation once (with an evidence photo) in a database, and alerts the safety supervisor on Telegram in real time.

## The idea

On a large construction site, HSE officers cannot watch every floor at every moment, and PPE violations are usually found late, after the risk has already happened. The cameras are already there; what is missing is something that watches them all the time.

SiteGuard AI turns existing site cameras into a safety assistant:

* **It sees** – a computer-vision model trained on construction-site images recognises helmets and safety vests, *and* their absence, on every worker in view.
* **It is careful** – a violation is only raised when the missing PPE is detected consistently for a few seconds. When the picture is unclear, the worker is shown as *UNKNOWN* instead of creating a false alarm.
* **It remembers** – each worker gets a temporary ID and is followed across the camera view and across cameras (person re-identification), so one incident is recorded once, not once per camera or per frame.
* **It acts** – the supervisor receives an instant Telegram alert with the photo, worker ID, camera, location and time, and the violation is managed in a dashboard until corrective action is recorded and it is closed.

The goal is to move PPE compliance from occasional spot checks to continuous, evidence-based monitoring with data the HSE team can act on: where, when and how often violations happen.

> **Status:** Phase 1 – working MVP, tested end-to-end on Windows 11 with a phone camera (Iriun Webcam). Phase 2 adds reports & analytics with Excel / PDF export.

---

## 1. Required software

| Software | Notes |
|---|---|
| Windows 10 / 11 (64-bit) | Tested target: Windows 11 |
| Python **3.10 – 3.13** (64-bit) | 3.12 recommended. `install.bat` can install it for you with winget |
| Internet connection | Only for the first installation (~1 GB of Python packages) |
| Iriun Webcam | PC app + phone app, for the demo camera (https://iriun.com) |
| Google Chrome / Edge | To open the dashboard |
| Telegram (optional) | For mobile alerts |

Node.js is **not** needed: the dashboard is already built (`frontend/dist`). Node is only needed if you want to modify the frontend (see *Development*).

## 2. Python installation

1. Download Python 3.12 from https://www.python.org/downloads/windows/ (Windows installer 64-bit).
2. During setup tick **"Add python.exe to PATH"**.
3. Or simply run `install.bat` – if Python is missing it offers to install Python 3.12 automatically (winget).

## 3. Install the dependencies

Double-click **`install.bat`**. It will:

1. find a compatible Python,
2. create a private virtual environment in `.venv` (nothing is installed system-wide),
3. install everything from `requirements.txt` (PyTorch, Ultralytics YOLO, OpenCV, ONNX Runtime, FastAPI …),
4. create `.env` from `.env.example`,
5. run the environment check (loads the AI models, measures AI speed, lists the cameras Windows can see).

You can re-run the check at any time with **`check.bat`**.

## 4. AI models (download & configuration)

`install.bat` downloads the two YOLO models from their original sources into the `models` folder (`tools/download_models.py`). The Re-ID model is included in the repository (split into two parts that are joined automatically on first start).

| File | Purpose | Source |
|---|---|---|
| `ppe_yolov8n.pt` | **PPE detection** – YOLOv8 trained on the Roboflow *Construction Site Safety* dataset. Classes: `Hardhat`, `NO-Hardhat`, `Safety Vest`, `NO-Safety Vest`, `Person`, `Mask`, `NO-Mask`, `Safety Cone`, `machinery`, `vehicle` | github.com/snehilsanyal/Construction-Site-Safety-PPE-Detection |
| `person_yolov8n_coco.pt` | Robust person detection for tracking (COCO) | Ultralytics YOLOv8n |
| `reid_lmbn_n_market.onnx` | Person **Re-Identification** (appearance embedding, 3584-d) – LMBN-n trained on Market-1501, exported to ONNX | BoxMOT model zoo (`tools/export_reid_onnx.py`) |

**How violations are decided (no fake detection):**
* A violation is raised **only** when the PPE model positively detects the *absence* of an item (`NO-Hardhat`, `NO-Safety Vest`) on a tracked worker, consistently over several frames (default: 60 % of the last 8 AI frames) **and** for at least 2 seconds.
* If the model cannot see enough (head not visible, too far, mixed results) the worker is shown as **PPE UNKNOWN** (amber) and **nothing is recorded**.
* Green box = PPE COMPLIANT, red box = NO HELMET / NO SAFETY VEST DETECTED (with confidence %).
* Safety shoes: the included model has no shoe classes, so shoes are not checked. The engine already understands models with `shoes` / `no_shoes` classes (future).

**Use another / better PPE model:** copy the `.pt` file into `models` and set `PPE_MODEL_PATH=models/your_model.pt` in `.env`. Class names such as `helmet`, `no_helmet`, `head`, `vest`, `no_vest`, `shoes`, `no_shoes` are recognised automatically. `tools/download_models.py --force` re-downloads the YOLO models.

**GPU (optional):** on a PC with an NVIDIA GPU you can install the CUDA build of PyTorch for much faster detection:
`.venv\Scripts\python.exe -m pip install --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu128` (pick the CUDA version shown on https://pytorch.org/get-started/locally/). The system uses the GPU automatically (`INFERENCE_DEVICE=auto`).

## 5. Connect Iriun Webcam

1. Install **Iriun Webcam** on the PC (iriun.com) and on the phone (App Store / Google Play).
2. Connect the phone and PC to the **same Wi-Fi** (or USB), open the app on both. The PC app must show the phone's video.
3. Run `check.bat` – the camera list should show e.g. `[1] Iriun Webcam - working, 1280x720   <-- Iriun Webcam`.
4. In the dashboard: **Cameras → Add Camera**, *Source type* = **Local webcam**, press **Detect**, choose **Iriun Webcam**, fill in the name and location (e.g. *Camera 01 – Tower B - Level 8*), **Save**, then **Start**.
5. Open **Live Monitoring**. Stand in front of the phone camera:
   * wearing helmet + vest → green **PPE COMPLIANT**
   * remove the helmet → red **NO HELMET DETECTED**; after ~2 s a violation is registered with an evidence photo (and a Telegram alert, if configured)
   * put the helmet back on → the box returns to green within ~1 s.

Tips: stand 1.5–4 m from the camera so your head **and** torso are visible; good lighting helps. If only your face is visible the vest cannot be judged (shown as `Vest: ?`). You can untick *Safety Vest* in **Settings → Required PPE** to test helmets only.

**CCTV / IP cameras:** *Source type* **RTSP stream**, e.g. `rtsp://user:password@192.168.1.64:554/Streaming/Channels/101` (Hikvision) or `rtsp://user:password@IP:554/cam/realmonitor?channel=1&subtype=0` (Dahua). **HTTP / MJPEG** URLs are also supported. Lost streams reconnect automatically.

## 6. Start the application

Double-click **`start.bat`**. The dashboard opens automatically at **http://127.0.0.1:8000**. Keep the black window open; close it (or press Ctrl+C) to stop the system.

Cameras with *Start automatically* enabled start when the system starts.
To open the dashboard from another device on the network set `APP_HOST=0.0.0.0` in `.env` and browse to `http://<PC-IP>:8000` (allow Python in Windows Firewall).

## 7. Telegram notifications

1. In Telegram, talk to **@BotFather** → `/newbot` → copy the **Bot Token**.
2. Open your new bot and press **Start** (or add the bot to your HSE group).
3. Get the **Chat ID**: open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser after sending the bot a message and read `"chat":{"id": ...}` (group IDs start with `-100`). Alternatively talk to **@userinfobot**.
4. Dashboard → **Settings → Telegram Notifications**: paste Token and Chat ID, tick *Send violation alerts to Telegram*, **Save Settings**, then **Send Test Message**.

Each alert contains: violation type, Worker ID, camera, project location, date & time, confidence, status and the evidence photo. The token is stored in the local database and is never shown again in full (masked as `1234****abcd`).

## 8. Troubleshooting

| Problem | Solution |
|---|---|
| `install.bat` cannot find Python | Install Python 3.12 64-bit with "Add to PATH", or accept the winget installation |
| No camera in the list | Start Iriun on PC **and** phone first; close other apps using the camera (Zoom, Teams, Camera app); press **Detect** again; run `check.bat` |
| Camera shows *NO SIGNAL / Reconnecting* | The webcam is busy or disconnected – Iriun phone app closed / phone locked. The system retries automatically |
| Black image from Iriun | Open the Iriun PC app and make sure it shows video; restart the Iriun app |
| Wrong camera opens | Each webcam has an index – edit the camera and choose the correct device |
| RTSP camera does not connect | Test the URL in VLC (Media → Open Network Stream); check user/password, IP and that the PC is on the same network |
| Helmet not recognised / always UNKNOWN | Improve lighting, stand so head and shoulders are clearly visible, lower *PPE present/missing confidence* in Settings (e.g. 0.35) |
| False violations | Raise *PPE missing confidence* (e.g. 0.6) or *Violation must persist* (e.g. 3 s) |
| Slow video / low AI FPS | Lower *AI input size* to 480, use *PPE model Person class* as person detector, or install the GPU version of PyTorch |
| Telegram test fails | Check token & chat ID, press Start in the bot chat, check the internet / firewall |
| Port 8000 busy | Set `APP_PORT=8010` in `.env` |
| Anything else | See `logs\app.log` |

---

## Features (Phase 1)

* Live video with green / red / amber boxes, worker IDs, PPE status and confidence %
* Real PPE detection (helmet + safety vest) – YOLOv8 PPE model, no simulated results
* Worker tracking: **ByteTrack** + person **Re-ID** (LMBN, ONNX) – temporary Worker IDs (`W-101` …), recognition of the same worker when they return or appear on another camera
* Identity safety: Re-ID only links two sightings when similarity is high **and** clearly better than any other candidate; otherwise a new Worker ID is created. Tracks are re-verified by appearance every ~2 s, so an ID never silently jumps to another person
* Duplicate prevention: one violation per *worker + violation type* incident; new sightings (any camera) update the existing record (sightings counter, cameras involved) – configurable window and notification cooldown
* Automatic evidence photo (`data/violations/YYYY-MM-DD/`) with banner: violation ID, type, worker, camera, location, time
* SQLite database (`data/monitoring.db`) – PostgreSQL-ready (`DATABASE_URL`)
* Dashboard: KPIs, live camera, latest alerts, hourly / type / 7-day charts, camera status, real-time activity feed (WebSockets), pop-up + sound alerts
* Violation management: filters, search, evidence viewer, status *Open / Under Review / Closed*, corrective action (required to close), supervisor notes
* Camera management: add / edit / remove, local webcams (auto-detected by name), RTSP, HTTP/MJPEG, video files; start / stop; auto-start; auto-reconnect
* Telegram alerts with photo; settings page for all thresholds

## Architecture

```
Camera (Iriun / RTSP) ──► capture thread ──► live MJPEG stream (annotated) ──► Browser (React)
                               │ newest frame                                     ▲
                               ▼                                                  │ WebSocket events
                         AI thread: YOLOv8 PPE + YOLOv8 person ─► ByteTrack ─► PPE association
                               │            ▲                                     │
                               │      Re-ID thread (LMBN ONNX embeddings)         ▼
                               └─► temporal PPE decision ─► Violation manager ─► SQLite + evidence JPG
                                                                     └─► Notification dispatcher ─► Telegram
```

```
Monitoring System/
├── backend/
│   ├── main.py                  FastAPI app (REST + WebSocket + MJPEG + dashboard)
│   ├── config.py                paths & default settings     settings_store.py  runtime settings (DB)
│   ├── camera/                  sources.py (webcams/RTSP)  worker.py (capture + AI + Re-ID threads)  manager.py
│   ├── detection/               ppe_detector.py (YOLO, PPE↔person association)  annotator.py (drawing)
│   ├── tracking/                tracker.py (ByteTrack)  reid.py (Re-ID + worker registry)  ppe_state.py
│   ├── violations/              manager.py (registration, evidence, duplicate prevention)
│   ├── notifications/           telegram.py  dispatcher.py (add push / e-mail channels here)
│   ├── database/                db.py  models.py
│   ├── api/                     cameras.py  violations.py  dashboard.py  system.py
│   └── selfcheck.py             environment check (check.bat)
├── frontend/                    React + Vite source (src/) and built dashboard (dist/)
├── models/                      AI models
├── data/                        monitoring.db + violations/ (evidence photos)
├── reports/  logs/  config/
├── tests/                       test_violation_rules.py, pipeline_harness.py
├── tools/                       download_models.py, export_reid_onnx.py
├── requirements.txt  .env.example  install.bat  start.bat  check.bat
```

API documentation (Swagger) is available at http://127.0.0.1:8000/docs.

## Tests

```
.venv\Scripts\python.exe -m tests.test_violation_rules          # database registration + duplicate prevention
.venv\Scripts\python.exe -m tests.pipeline_harness <video.mp4>   # full AI pipeline on a video file, prints worker IDs / decisions
```

## Development (frontend)

Install Node.js 20+, then:
```
cd frontend
npm install
npm run dev      # http://localhost:5173 (proxies the backend on port 8000)
npm run build    # rebuild frontend/dist used by start.bat
```

## Known limitations (Phase 1)

* Re-ID is appearance-based: workers in identical uniforms, heavily overlapping people or very small (far) people may receive a new Worker ID rather than being matched. This is intentional – a missed match creates one extra record; a wrong match would blame the wrong worker.
* Safety shoes need a model with shoe classes.
* CPU-only PCs process roughly 4–10 AI frames per second per camera; use a GPU for many cameras.
* Reports export (Excel / PDF) and advanced analytics are Phase 2.

## Credits & licence

* PPE detection model: [Construction-Site-Safety-PPE-Detection](https://github.com/snehilsanyal/Construction-Site-Safety-PPE-Detection) (YOLOv8, Roboflow *Construction Site Safety* dataset) – downloaded from its original repository at install time.
* [Ultralytics YOLO](https://github.com/ultralytics/ultralytics) (detection, ByteTrack implementation) – AGPL-3.0.
* Re-ID network LMBN-n from the [BoxMOT](https://github.com/mikel-brostrom/boxmot) model zoo – AGPL-3.0.

Because it builds on AGPL-3.0 components, this project is released under the **GNU AGPL-3.0** (see `LICENSE`).

## Phase 2 (next)

Reports & analytics (locations, floors, towers, hours, days, weekly / monthly trends, camera performance) with Excel / PDF export, mobile push notifications, user accounts & roles, PostgreSQL deployment, multi-camera GPU server.
