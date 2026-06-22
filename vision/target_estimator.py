from __future__ import annotations

from dataclasses import dataclass

from vision.dirt_detector_base import BBox, DirtDetectionResult, Point


@dataclass(slots=True)
class TargetEstimate:
    found: bool
    centroid: Point | None
    bbox: BBox | None
    area: float
    confidence: float
    error_x: float | None
    error_y: float | None


def estimate_target(result: DirtDetectionResult, frame_width: int, frame_height: int) -> TargetEstimate:
    if not result.found or result.centroid is None:
        return TargetEstimate(
            found=False,
            centroid=None,
            bbox=None,
            area=0.0,
            confidence=0.0,
            error_x=None,
            error_y=None,
        )

    cx, cy = result.centroid
    center_x = frame_width / 2.0
    center_y = frame_height / 2.0
    return TargetEstimate(
        found=True,
        centroid=result.centroid,
        bbox=result.bbox,
        area=result.area,
        confidence=result.confidence,
        error_x=float(cx - center_x),
        error_y=float(cy - center_y),
    )
