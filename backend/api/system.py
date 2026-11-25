from __future__ import annotations

import asyncio
import platform

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from backend import settings_store
from backend.camera.manager import manager
from backend.config import APP_NAME, APP_VERSION, VIOLATION_STATUSES, VIOLATION_TYPES
from backend.events import bus
from backend.notifications.telegram import TelegramNotifier

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health():
    return {"status": "ok", "app": APP_NAME, "version": APP_VERSION}


@router.get("/api/system/info")
def system_info():
    import cv2

    try:
        import torch

        torch_v, cuda = torch.__version__, torch.cuda.is_available()
    except Exception:  # noqa: BLE001
        torch_v, cuda = None, False
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "python": platform.python_version(),
        "os": f"{platform.system()} {platform.release()}",
        "opencv": cv2.__version__,
        "torch": torch_v,
        "cuda_available": cuda,
        "ai": {**manager.services.engine.info(), "loading": manager.models_loading},
        "reid": {"ready": manager.services.reid.ready, "error": manager.services.reid.error,
                 "model": manager.services.reid.model_path.name},
        "registry": manager.services.registry.stats(),
        "violation_types": VIOLATION_TYPES,
        "violation_statuses": VIOLATION_STATUSES,
    }


@router.get("/api/settings")
def get_settings():
    return settings_store.public_settings()


@router.put("/api/settings")
def put_settings(changes: dict):
    try:
        settings_store.update_settings(changes)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    bus.publish("settings_updated", {}, activity="Settings updated")
    return settings_store.public_settings()


@router.post("/api/settings/telegram/test")
async def telegram_test(body: dict | None = None):
    s = settings_store.get_settings()
    body = body or {}
    token = body.get("telegram_bot_token") or s["telegram_bot_token"]
    if token and "****" in token:
        token = s["telegram_bot_token"]
    chat = body.get("telegram_chat_id") or s["telegram_chat_id"]
    if not token or not chat:
        raise HTTPException(400, "Enter the Bot Token and Chat ID first")
    try:
        result = await asyncio.to_thread(TelegramNotifier(token, chat).test)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Telegram test failed: {e}") from e
    return {"ok": True, **result}


@router.get("/api/activity")
def activity():
    return list(bus.activity)


@router.websocket("/ws")
async def websocket(ws: WebSocket):
    await ws.accept()
    q = bus.subscribe()
    try:
        await ws.send_json({"type": "hello", "data": {"app": APP_NAME}})
        while True:
            msg = await q.get()
            await ws.send_text(msg)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        bus.unsubscribe(q)
