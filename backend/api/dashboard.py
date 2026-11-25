from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import func

from backend.camera.manager import manager
from backend.config import VIOLATION_TYPES
from backend.database.db import session_scope
from backend.database.models import Camera, DetectionStat, Violation, Worker
from backend.events import bus

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _today_start() -> datetime:
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/summary")
def summary():
    today = _today_start()
    with session_scope() as s:
        cams = s.query(Camera).order_by(Camera.name).all()
        cam_rows = [{**c.to_dict(), "runtime": manager.status(c.id)} for c in cams]
        status_counts = dict(s.query(Violation.status, func.count(Violation.id)).group_by(Violation.status).all())
        today_count = s.query(func.count(Violation.id)).filter(Violation.detected_at >= today).scalar() or 0
        workers_today = s.query(func.count(Worker.id)).filter(Worker.last_seen >= today).scalar() or 0
        workers_total = s.query(func.count(Worker.id)).scalar() or 0
        latest = [v.to_dict() for v in s.query(Violation).order_by(Violation.detected_at.desc(), Violation.id.desc()).limit(8)]
    connected = sum(1 for c in cam_rows if c["runtime"]["status"] == "online")
    live_workers = sum(c["runtime"].get("persons", 0) for c in cam_rows)
    return {
        "total_cameras": len(cam_rows),
        "connected_cameras": connected,
        "workers_detected_today": workers_today,
        "workers_detected_total": workers_total,
        "workers_in_view": live_workers,
        "violations_today": today_count,
        "open_violations": status_counts.get("Open", 0),
        "under_review_violations": status_counts.get("Under Review", 0),
        "closed_violations": status_counts.get("Closed", 0),
        "latest_violations": latest,
        "cameras": cam_rows,
        "activity": list(bus.activity)[:30],
        "duplicates_suppressed": manager.services.violations.suppressed_duplicates,
        "active_incidents": manager.services.violations.active_incidents(),
        "ai": {**manager.services.engine.info(), "reid_ready": manager.services.reid.ready,
               "reid_error": manager.services.reid.error, "loading": manager.models_loading},
    }


@router.get("/charts")
def charts():
    today = _today_start()
    week_start = today - timedelta(days=6)
    with session_scope() as s:
        today_rows = s.query(Violation.detected_at, Violation.violation_type).filter(Violation.detected_at >= today).all()
        week_rows = s.query(Violation.detected_at, Violation.violation_type).filter(Violation.detected_at >= week_start).all()
        loc_rows = s.query(Violation.location, func.count(Violation.id)).filter(Violation.detected_at >= week_start) \
            .group_by(Violation.location).order_by(func.count(Violation.id).desc()).limit(8).all()
        det = s.query(DetectionStat.hour, func.sum(DetectionStat.person_detections), func.sum(DetectionStat.frames_processed)) \
            .filter(DetectionStat.hour >= today).group_by(DetectionStat.hour).all()

    hourly = [{"hour": f"{h:02d}:00", "helmet": 0, "vest": 0, "total": 0} for h in range(24)]
    for dt, vt in today_rows:
        row = hourly[dt.hour]
        row[vt] = row.get(vt, 0) + 1
        row["total"] += 1
    by_type = Counter(vt for _, vt in week_rows)
    daily = []
    for i in range(7):
        d = week_start + timedelta(days=i)
        cnt = Counter(vt for dt, vt in week_rows if dt.date() == d.date())
        daily.append({"day": d.strftime("%a %d"), "helmet": cnt.get("helmet", 0), "vest": cnt.get("vest", 0),
                      "total": sum(cnt.values())})
    activity = [{"hour": f"{h:02d}:00", "detections": 0} for h in range(24)]
    for hour, persons, frames in det:
        activity[hour.hour]["detections"] = int(persons or 0)
    return {
        "hourly_today": hourly,
        "by_type_7d": [{"type": VIOLATION_TYPES.get(k, k), "key": k, "count": v} for k, v in by_type.items()],
        "daily_7d": daily,
        "by_location_7d": [{"location": loc or "Unassigned", "count": c} for loc, c in loc_rows],
        "detection_activity_today": activity,
    }
