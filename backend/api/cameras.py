from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from backend.camera.manager import manager
from backend.camera.sources import list_webcams
from backend.database.db import session_scope
from backend.database.models import Camera
from backend.events import bus

router = APIRouter(prefix="/api", tags=["cameras"])


class CameraIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    location: str = Field(default="", max_length=200)
    tower: str = Field(default="", max_length=100)
    floor: str = Field(default="", max_length=100)
    source_type: str = "webcam"
    source: str = "0"
    enabled: bool = True
    auto_start: bool = False

    @field_validator("source_type")
    @classmethod
    def _type(cls, v):
        if v not in ("webcam", "rtsp", "http", "file"):
            raise ValueError("source_type must be webcam, rtsp, http or file")
        return v

    @field_validator("name", "location", "tower", "floor", "source")
    @classmethod
    def _strip(cls, v):
        return v.strip()


def _validate_source(data: CameraIn):
    if data.source_type == "webcam" and not data.source.isdigit():
        raise HTTPException(400, "Webcam source must be the device index (0, 1, 2 ...)")
    if data.source_type == "rtsp" and not data.source.lower().startswith("rtsp://"):
        raise HTTPException(400, "RTSP source must start with rtsp://")
    if data.source_type == "http" and not data.source.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "HTTP source must start with http:// or https://")


def _camera_out(c: Camera) -> dict:
    return {**c.to_dict(), "runtime": manager.status(c.id)}


@router.get("/cameras")
def list_cameras():
    with session_scope() as s:
        return [_camera_out(c) for c in s.query(Camera).order_by(Camera.name).all()]


@router.post("/cameras", status_code=201)
def create_camera(data: CameraIn):
    _validate_source(data)
    with session_scope() as s:
        if s.query(Camera).filter(Camera.name == data.name).first():
            raise HTTPException(409, f"A camera named '{data.name}' already exists")
        cam = Camera(**data.model_dump())
        s.add(cam)
        s.flush()
        out = _camera_out(cam)
    bus.publish("camera_added", out, activity=f"Camera added: {out['name']} ({out['location']})")
    return out


@router.put("/cameras/{camera_id}")
def update_camera(camera_id: int, data: CameraIn):
    _validate_source(data)
    with session_scope() as s:
        cam = s.get(Camera, camera_id)
        if not cam:
            raise HTTPException(404, "Camera not found")
        dup = s.query(Camera).filter(Camera.name == data.name, Camera.id != camera_id).first()
        if dup:
            raise HTTPException(409, f"A camera named '{data.name}' already exists")
        for k, v in data.model_dump().items():
            setattr(cam, k, v)
    if not data.enabled:
        manager.stop(camera_id)
    else:
        manager.restart_if_running(camera_id)
    with session_scope() as s:
        return _camera_out(s.get(Camera, camera_id))


@router.delete("/cameras/{camera_id}")
def delete_camera(camera_id: int):
    manager.remove(camera_id)
    with session_scope() as s:
        cam = s.get(Camera, camera_id)
        if not cam:
            raise HTTPException(404, "Camera not found")
        name = cam.name
        s.delete(cam)
    bus.publish("camera_removed", {"id": camera_id}, activity=f"Camera removed: {name}")
    return {"ok": True}


@router.post("/cameras/{camera_id}/start")
def start_camera(camera_id: int):
    if not manager.services.engine.ready and not manager.models_loading:
        raise HTTPException(503, f"AI engine is not ready: {manager.services.engine.error}")
    try:
        return manager.start(camera_id)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/cameras/{camera_id}/stop")
def stop_camera(camera_id: int):
    return manager.stop(camera_id)


@router.get("/cameras/{camera_id}/snapshot")
def snapshot(camera_id: int):
    w = manager.workers.get(camera_id)
    if not w or not w.jpeg:
        raise HTTPException(404, "No image available - start the camera first")
    return Response(content=w.jpeg, media_type="image/jpeg")


@router.get("/cameras/{camera_id}/stream")
async def stream(camera_id: int, request: Request):
    """Annotated live video as MJPEG (multipart/x-mixed-replace)."""

    async def gen():
        last = -1
        idle = 0.0
        while True:
            if await request.is_disconnected():
                break
            w = manager.workers.get(camera_id)
            if w is not None and w.jpeg and w.jpeg_seq != last:
                last = w.jpeg_seq
                idle = 0.0
                yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(w.jpeg)).encode()
                       + b"\r\n\r\n" + w.jpeg + b"\r\n")
            else:
                await asyncio.sleep(0.03)
                idle += 0.03
                if idle > 30 and (w is None or not w.running):
                    break

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-cache, no-store", "Pragma": "no-cache"})


@router.get("/devices/webcams")
async def webcams():
    """Detect local cameras (USB webcams, Iriun Webcam, OBS virtual camera, ...)."""
    busy = manager.busy_webcams()
    return await asyncio.to_thread(list_webcams, 6, busy, True)
