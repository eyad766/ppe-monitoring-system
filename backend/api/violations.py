from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_

from backend.config import VIOLATION_STATUSES, VIOLATIONS_DIR
from backend.database.db import session_scope
from backend.database.models import Violation, now
from backend.events import bus
from backend.violations.manager import violation_manager

router = APIRouter(prefix="/api/violations", tags=["violations"])
log = logging.getLogger("api.violations")


class ViolationUpdate(BaseModel):
    status: str | None = None
    corrective_action: str | None = None
    supervisor_notes: str | None = None


@router.get("")
def list_violations(
    status: str | None = None,
    violation_type: str | None = None,
    camera_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
):
    with session_scope() as s:
        q = s.query(Violation)
        if status:
            q = q.filter(Violation.status == status)
        if violation_type:
            q = q.filter(Violation.violation_type == violation_type)
        if camera_id:
            q = q.filter(Violation.camera_id == camera_id)
        if date_from:
            q = q.filter(Violation.detected_at >= datetime.combine(date_from, datetime.min.time()))
        if date_to:
            q = q.filter(Violation.detected_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
        if search:
            like = f"%{search.strip()}%"
            q = q.filter(or_(Violation.code.ilike(like), Violation.worker_code.ilike(like),
                             Violation.camera_name.ilike(like), Violation.location.ilike(like),
                             Violation.violation_label.ilike(like)))
        total = q.count()
        rows = q.order_by(Violation.detected_at.desc(), Violation.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return {"total": total, "page": page, "page_size": page_size, "items": [r.to_dict() for r in rows]}


@router.get("/{violation_id}")
def get_violation(violation_id: int):
    with session_scope() as s:
        v = s.get(Violation, violation_id)
        if not v:
            raise HTTPException(404, "Violation not found")
        return v.to_dict()


@router.delete("/{violation_id}")
def delete_violation(violation_id: int):
    """Permanently delete a violation record and its evidence image."""
    with session_scope() as s:
        v = s.get(Violation, violation_id)
        if not v:
            raise HTTPException(404, "Violation not found")
        code, evidence = v.code, v.evidence_path
        s.delete(v)
    if evidence:
        try:
            path = (VIOLATIONS_DIR / evidence).resolve()
            if VIOLATIONS_DIR.resolve() in path.parents and path.is_file():
                path.unlink()
        except OSError:
            log.warning("Could not delete evidence file %s", evidence)
    # forget the in-memory incident so the same worker can be recorded again if the violation recurs
    violation_manager.on_violation_closed(violation_id)
    log.info("Violation %s deleted by user", code)
    bus.publish("violation_deleted", {"id": violation_id, "code": code}, activity=f"{code} deleted", level="warning")
    return {"ok": True, "id": violation_id, "code": code}


@router.patch("/{violation_id}")
def update_violation(violation_id: int, data: ViolationUpdate):
    with session_scope() as s:
        v = s.get(Violation, violation_id)
        if not v:
            raise HTTPException(404, "Violation not found")
        if data.status is not None:
            if data.status not in VIOLATION_STATUSES:
                raise HTTPException(400, f"Status must be one of {VIOLATION_STATUSES}")
            if data.status == "Closed" and not ((data.corrective_action if data.corrective_action is not None
                                                 else v.corrective_action) or "").strip():
                raise HTTPException(400, "Describe the corrective action before closing the violation")
            v.status = data.status
            v.closed_at = now() if data.status == "Closed" else None
        if data.corrective_action is not None:
            v.corrective_action = data.corrective_action.strip()
        if data.supervisor_notes is not None:
            v.supervisor_notes = data.supervisor_notes.strip()
        out = v.to_dict()
    if out["status"] == "Closed":
        violation_manager.on_violation_closed(violation_id)
    bus.publish("violation_updated", out, activity=f"{out['code']} updated - status: {out['status']}")
    return out
