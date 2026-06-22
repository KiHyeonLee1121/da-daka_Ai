from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class PanelROI:
    x: int
    y: int
    w: int
    h: int

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.w, self.h


class PanelDetector:
    """Initial MVP ROI selector.

    The MVP can treat the whole frame as the acrylic mock panel. Manual ROI is
    useful when the test plate occupies only part of the camera frame, and the
    extension point remains open for later contour/grid based panel detection.
    """

    def __init__(self, roi_config: dict[str, Any]):
        self.config = roi_config

    def detect(self, frame: Any) -> PanelROI | None:
        height, width = frame.shape[:2]
        if self.config.get("use_manual_roi", False):
            x = int(self.config.get("x", 0))
            y = int(self.config.get("y", 0))
            w = int(self.config.get("w", width))
            h = int(self.config.get("h", height))
        else:
            x, y, w, h = 0, 0, width, height

        x = max(0, min(x, width - 1))
        y = max(0, min(y, height - 1))
        w = max(1, min(w, width - x))
        h = max(1, min(h, height - y))
        return PanelROI(x=x, y=y, w=w, h=h)
