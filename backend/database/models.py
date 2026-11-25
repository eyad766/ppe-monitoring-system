"""ORM models. Timestamps are stored as local (site) time."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.db import Base


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    location: Mapped[str] = mapped_column(String(200), default="")
    tower: Mapped[str] = mapped_column(String(100), default="")
    floor: Mapped[str] = mapped_column(String(100), default="")
    source_type: Mapped[str] = mapped_column(String(20), default="webcam")  # webcam | rtsp | http | file
    source: Mapped[str] = mapped_column(String(500), default="0")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_start: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "location": self.location,
            "tower": self.tower,
            "floor": self.floor,
            "source_type": self.source_type,
            "source": self.source,
            "enabled": self.enabled,
            "auto_start": self.auto_start,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Worker(Base):
    """A temporary worker identity created by the tracking / Re-ID engine."""

    __tablename__ = "workers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=now)
    first_camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cameras_seen: Mapped[list] = mapped_column(JSON, default=list)


class Violation(Base):
    __tablename__ = "violations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True, default="")
    worker_id: Mapped[int | None] = mapped_column(ForeignKey("workers.id"), nullable=True)
    worker_code: Mapped[str] = mapped_column(String(20), index=True)
    violation_type: Mapped[str] = mapped_column(String(30), index=True)  # helmet | vest
    violation_label: Mapped[str] = mapped_column(String(100))
    camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    camera_name: Mapped[str] = mapped_column(String(100))
    location: Mapped[str] = mapped_column(String(200), default="")
    tower: Mapped[str] = mapped_column(String(100), default="")
    floor: Mapped[str] = mapped_column(String(100), default="")
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    cameras_involved: Mapped[list] = mapped_column(JSON, default=list)
    evidence_path: Mapped[str] = mapped_column(String(500), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="Open", index=True)
    corrective_action: Mapped[str] = mapped_column(Text, default="")
    supervisor_notes: Mapped[str] = mapped_column(Text, default="")
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    notification_error: Mapped[str] = mapped_column(Text, default="")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    worker: Mapped[Worker | None] = relationship()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "code": self.code,
            "worker_id": self.worker_id,
            "worker_code": self.worker_code,
            "violation_type": self.violation_type,
            "violation_label": self.violation_label,
            "camera_id": self.camera_id,
            "camera_name": self.camera_name,
            "location": self.location,
            "tower": self.tower,
            "floor": self.floor,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "occurrences": self.occurrences,
            "cameras_involved": self.cameras_involved or [],
            "evidence_path": self.evidence_path or "",
            "evidence_url": f"/evidence/{self.evidence_path}" if self.evidence_path else None,
            "confidence": round(self.confidence or 0.0, 3),
            "status": self.status,
            "corrective_action": self.corrective_action or "",
            "supervisor_notes": self.supervisor_notes or "",
            "notified": self.notified,
            "notification_error": self.notification_error or "",
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[object] = mapped_column(JSON)


class DetectionStat(Base):
    """Per-camera, per-hour detection counters (used for activity charts and camera statistics)."""

    __tablename__ = "detection_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(Integer, index=True)
    hour: Mapped[datetime] = mapped_column(DateTime, index=True)
    frames_processed: Mapped[int] = mapped_column(Integer, default=0)
    person_detections: Mapped[int] = mapped_column(Integer, default=0)
    compliant_observations: Mapped[int] = mapped_column(Integer, default=0)
    violation_observations: Mapped[int] = mapped_column(Integer, default=0)
    unknown_observations: Mapped[int] = mapped_column(Integer, default=0)
