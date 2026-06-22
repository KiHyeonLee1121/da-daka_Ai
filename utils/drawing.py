from __future__ import annotations

from typing import Any


def draw_debug_overlay(
    frame: Any,
    panel_roi: Any,
    detection: Any,
    target: Any,
    lidar: Any,
    command: Any,
    state: Any,
    dry_run: bool,
) -> Any:
    import cv2

    out = frame.copy()
    height, width = out.shape[:2]

    if panel_roi is not None:
        x, y, w, h = panel_roi.as_tuple()
        cv2.rectangle(out, (x, y), (x + w, y + h), (0, 220, 220), 1)

    center = (width // 2, height // 2)
    cv2.drawMarker(out, center, (255, 255, 255), markerType=cv2.MARKER_CROSS, markerSize=18, thickness=1)

    if getattr(detection, "found", False):
        for candidate in getattr(detection, "candidates", [])[:5]:
            bx, by, bw, bh = candidate.bbox
            cv2.rectangle(out, (bx, by), (bx + bw, by + bh), (160, 120, 0), 1)

        if detection.bbox is not None:
            bx, by, bw, bh = detection.bbox
            cv2.rectangle(out, (bx, by), (bx + bw, by + bh), (0, 255, 0), 2)
        if detection.centroid is not None:
            cx, cy = detection.centroid
            cv2.circle(out, (cx, cy), 5, (0, 0, 255), -1)
            cv2.line(out, center, (cx, cy), (0, 0, 255), 1)

    lines = [
        f"state: {getattr(state, 'value', state)} | mode: {'DRY-RUN' if dry_run else 'LIVE'}",
        f"dirt: {bool(getattr(detection, 'found', False))} area: {getattr(detection, 'area', 0.0):.1f} conf: {getattr(detection, 'confidence', 0.0):.2f}",
        f"error: x={_fmt(getattr(target, 'error_x', None))} y={_fmt(getattr(target, 'error_y', None))}",
        f"lidar: {_fmt(getattr(lidar, 'distance_m', None))} m valid={getattr(lidar, 'valid', False)}",
        f"cmd: {getattr(getattr(command, 'command_type', None), 'value', None)} vx={getattr(command, 'vx', 0.0):.2f} vy={getattr(command, 'vy', 0.0):.2f} vz={getattr(command, 'vz', 0.0):.2f}",
    ]

    y0 = 22
    for i, line in enumerate(lines):
        y = y0 + i * 22
        cv2.putText(out, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(out, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

    return out


def _fmt(value: Any) -> str:
    if value is None:
        return "None"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)
