"""Drawing helpers for live video overlays and evidence images (OpenCV only, no external fonts)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import cv2
import numpy as np

GREEN = (60, 200, 60)
RED = (40, 40, 230)
AMBER = (0, 170, 255)
GREY = (170, 170, 170)
WHITE = (255, 255, 255)
DARK = (25, 25, 25)

STATUS_COLORS = {"COMPLIANT": GREEN, "VIOLATION": RED, "UNKNOWN": AMBER, "IDENTIFYING": GREY}


@dataclass
class OverlayItem:
    xyxy: tuple[int, int, int, int]
    status: str  # COMPLIANT | VIOLATION | UNKNOWN | IDENTIFYING
    title: str
    lines: list[str] = field(default_factory=list)
    gear: list[tuple[tuple[int, int, int, int], tuple[int, int, int], str]] = field(default_factory=list)
    track_id: int = -1


def _scale(frame: np.ndarray) -> float:
    return max(0.5, min(1.4, frame.shape[1] / 1280.0 * 1.1))


def _label(img, text, x, y, color, scale, thickness=1, above=True):
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), base = cv2.getTextSize(text, font, scale, thickness)
    pad = int(4 * scale) + 2
    y_top = y - th - 2 * pad if above else y
    y_top = max(0, y_top)
    x = int(max(0, min(x, img.shape[1] - tw - 2 * pad)))
    cv2.rectangle(img, (x, y_top), (x + tw + 2 * pad, y_top + th + 2 * pad), color, -1)
    cv2.putText(img, text, (x + pad, y_top + th + pad), font, scale, WHITE if color != AMBER else DARK, thickness, cv2.LINE_AA)
    return y_top, y_top + th + 2 * pad


def draw_items(frame: np.ndarray, items: list[OverlayItem], highlight_track: int | None = None) -> np.ndarray:
    s = _scale(frame)
    for it in items:
        for (g, gcol, gtxt) in it.gear:
            cv2.rectangle(frame, g[:2], g[2:], gcol, max(1, int(1.5 * s)))
            if gtxt:
                cv2.putText(frame, gtxt, (g[0], max(10, g[1] - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.42 * s, gcol, 1, cv2.LINE_AA)
    for it in items:
        color = STATUS_COLORS.get(it.status, GREY)
        x1, y1, x2, y2 = it.xyxy
        thick = max(2, int(3 * s))
        if highlight_track is not None and it.track_id == highlight_track:
            thick = max(4, int(6 * s))
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thick)
        header = it.title + ("  |  " + it.lines[0] if it.lines else "")
        top, _ = _label(frame, header, x1, y1, color, 0.6 * s, max(1, int(1.6 * s)))
        if top <= 0 and y1 < 30:  # no room above -> draw inside the box
            _label(frame, header, x1, y1 + 2, color, 0.6 * s, max(1, int(1.6 * s)), above=False)
        extras = it.lines[1:]
        if extras:
            (_, th), _ = cv2.getTextSize("Ag", cv2.FONT_HERSHEY_SIMPLEX, 0.5 * s, 1)
            line_h = th + 2 * (int(4 * 0.5 * s) + 2)
            y = y2 if y2 + line_h * len(extras) <= frame.shape[0] else max(y1, y2 - line_h * len(extras))
            for extra in extras:
                _, y = _label(frame, extra, x1, y, color, 0.5 * s, 1, above=False)
    return frame


def draw_hud(frame: np.ndarray, camera_name: str, location: str, fps: float, persons: int, ai_ok: bool = True) -> np.ndarray:
    s = _scale(frame)
    text = f"{camera_name}  |  {location}  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    _label(frame, text, 8, 8, DARK, 0.5 * s, 1, above=False)
    right = f"AI {fps:.1f} FPS  |  Workers: {persons}" if ai_ok else "AI ENGINE NOT READY"
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, _), _ = cv2.getTextSize(right, font, 0.5 * s, 1)
    _label(frame, right, frame.shape[1] - tw - 20, 8, DARK if ai_ok else RED, 0.5 * s, 1, above=False)
    return frame


def render_evidence(frame: np.ndarray, items: list[OverlayItem], track_id: int, banner_lines: list[str]) -> np.ndarray:
    img = frame.copy()
    draw_items(img, items, highlight_track=track_id)
    s = _scale(img)
    font = cv2.FONT_HERSHEY_SIMPLEX
    line_h = int(26 * s)
    banner_h = line_h * len(banner_lines) + int(14 * s)
    out = np.zeros((img.shape[0] + banner_h, img.shape[1], 3), dtype=np.uint8)
    out[:banner_h] = (30, 30, 160)
    out[banner_h:] = img
    for i, line in enumerate(banner_lines):
        cv2.putText(out, line, (int(12 * s), int(8 * s) + line_h * (i + 1) - int(6 * s)), font,
                    (0.62 if i == 0 else 0.52) * s, WHITE, 2 if i == 0 else 1, cv2.LINE_AA)
    return out


def placeholder(text: str, sub: str = "", size=(1280, 720)) -> np.ndarray:
    img = np.full((size[1], size[0], 3), 32, dtype=np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX
    for i, (t, sc) in enumerate(((text, 1.2), (sub, 0.7))):
        if not t:
            continue
        (tw, th), _ = cv2.getTextSize(t, font, sc, 2)
        cv2.putText(img, t, ((size[0] - tw) // 2, size[1] // 2 + i * 50), font, sc, (200, 200, 200), 2, cv2.LINE_AA)
    return img
