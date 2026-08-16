"""Classical multi-panel rectangle detector for the 3 m survey image."""

from dataclasses import dataclass
import math

import cv2
import numpy as np


@dataclass(frozen=True)
class PanelRectangle:
    candidate_id: int
    x: int
    y: int
    width: int
    height: int
    confidence: float

    def normalized(self, image_width: int, image_height: int) -> dict:
        return {
            'candidate_id': self.candidate_id,
            'center_x_norm': (self.x + self.width / 2.0) / image_width,
            'center_y_norm': (self.y + self.height / 2.0) / image_height,
            'width_norm': self.width / image_width,
            'height_norm': self.height / image_height,
            'confidence': self.confidence,
        }


def select_panel_nearest_target(
    panels: list[PanelRectangle],
    *,
    image_width: int,
    image_height: int,
    target_x_norm: float,
    target_y_norm: float,
    maximum_distance_norm: float,
) -> PanelRectangle | None:
    """Select the panel nearest the expected camera/nozzle target point."""
    values = (target_x_norm, target_y_norm, maximum_distance_norm)
    if not all(math.isfinite(value) for value in values):
        raise ValueError('panel target selection values must be finite')
    if min(image_width, image_height) <= 0:
        raise ValueError('image dimensions must be positive')
    if not 0.0 <= target_x_norm <= 1.0 or not 0.0 <= target_y_norm <= 1.0:
        raise ValueError('panel target point must be normalized')
    if not 0.0 < maximum_distance_norm <= math.sqrt(2.0):
        raise ValueError('maximum panel target distance is invalid')
    if not panels:
        return None

    def score(panel: PanelRectangle) -> tuple[float, float, int]:
        center_x = (panel.x + panel.width / 2.0) / image_width
        center_y = (panel.y + panel.height / 2.0) / image_height
        distance = math.hypot(
            center_x - target_x_norm,
            center_y - target_y_norm,
        )
        return distance, -panel.confidence, panel.candidate_id

    selected = min(panels, key=score)
    return selected if score(selected)[0] <= maximum_distance_norm else None


class PanelDetector:
    """Find high-area quadrilateral candidates without assuming their layout."""

    def __init__(
        self,
        *,
        minimum_area_ratio: float,
        maximum_area_ratio: float,
        minimum_aspect_ratio: float,
        maximum_aspect_ratio: float,
        maximum_panels: int,
    ) -> None:
        if not 0.0 < minimum_area_ratio < maximum_area_ratio <= 1.0:
            raise ValueError('panel area ratio bounds are invalid')
        if not 0.0 < minimum_aspect_ratio < maximum_aspect_ratio:
            raise ValueError('panel aspect ratio bounds are invalid')
        if maximum_panels <= 0:
            raise ValueError('maximum_panels must be positive')
        self.minimum_area_ratio = minimum_area_ratio
        self.maximum_area_ratio = maximum_area_ratio
        self.minimum_aspect_ratio = minimum_aspect_ratio
        self.maximum_aspect_ratio = maximum_aspect_ratio
        self.maximum_panels = maximum_panels

    def detect(self, frame: np.ndarray) -> list[PanelRectangle]:
        if frame is None or frame.ndim != 3:
            raise ValueError('BGR frame is required')
        height, width = frame.shape[:2]
        frame_area = float(width * height)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 60, 160)
        edges = cv2.morphologyEx(
            edges,
            cv2.MORPH_CLOSE,
            np.ones((5, 5), dtype=np.uint8),
        )
        contours, _hierarchy = cv2.findContours(
            edges,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        candidates = []
        for contour in contours:
            area = float(cv2.contourArea(contour))
            area_ratio = area / frame_area
            if not self.minimum_area_ratio <= area_ratio <= self.maximum_area_ratio:
                continue
            perimeter = cv2.arcLength(contour, True)
            polygon = cv2.approxPolyDP(contour, 0.03 * perimeter, True)
            if len(polygon) != 4 or not cv2.isContourConvex(polygon):
                continue
            x, y, box_width, box_height = cv2.boundingRect(polygon)
            if min(box_width, box_height) <= 0:
                continue
            aspect = max(box_width, box_height) / min(box_width, box_height)
            if not self.minimum_aspect_ratio <= aspect <= self.maximum_aspect_ratio:
                continue
            rectangularity = min(1.0, area / float(box_width * box_height))
            confidence = max(0.01, min(1.0, rectangularity))
            candidates.append((area, x, y, box_width, box_height, confidence))
        candidates.sort(key=lambda value: (-value[0], value[1], value[2]))
        return [
            PanelRectangle(index, x, y, box_width, box_height, confidence)
            for index, (_area, x, y, box_width, box_height, confidence)
            in enumerate(candidates[:self.maximum_panels], 1)
        ]
