"""Low-overhead solar-panel ROI detection for the laptop perception pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import logging

import numpy as np

from laptop_ai.config import PanelConfig


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PanelROI:
    x: int
    y: int
    width: int
    height: int

    def validate(self, frame_width: int, frame_height: int) -> None:
        if min(self.x, self.y, self.width, self.height) < 0:
            raise ValueError("panel ROI values cannot be negative")
        if self.width < 1 or self.height < 1:
            raise ValueError("panel ROI must be non-empty")
        if self.x + self.width > frame_width or self.y + self.height > frame_height:
            raise ValueError("panel ROI exceeds frame bounds")


class PanelDetector:
    """Select a panel ROI without sending any control command.

    `contour` is the production-oriented mode: it searches for the largest
    rectangular contour that satisfies the configured frame-area and aspect-ratio
    constraints. `manual` and `full_frame` remain deterministic bench-test modes.
    If contour detection fails, the caller receives None and dirt inference is not
    allowed to create a target outside a confirmed panel ROI.
    """

    def __init__(self, config: PanelConfig) -> None:
        self.config = config

    def detect(self, frame: np.ndarray) -> PanelROI | None:
        if frame.ndim < 2:
            raise ValueError("frame must have image dimensions")
        frame_height, frame_width = frame.shape[:2]
        if frame_width < 1 or frame_height < 1:
            raise ValueError("frame dimensions must be positive")

        mode = self.config.mode
        if not self.config.enabled or mode == "full_frame":
            return PanelROI(0, 0, frame_width, frame_height)
        if mode == "manual":
            return self._manual(frame_width, frame_height)
        if mode == "contour":
            return self._contour(frame)
        raise ValueError(f"unsupported panel mode: {mode}")

    def _manual(self, frame_width: int, frame_height: int) -> PanelROI:
        x = max(0, min(self.config.manual_x, frame_width - 1))
        y = max(0, min(self.config.manual_y, frame_height - 1))
        width = max(1, min(self.config.manual_width, frame_width - x))
        height = max(1, min(self.config.manual_height, frame_height - y))
        return PanelROI(x, y, width, height)

    def _contour(self, frame: np.ndarray) -> PanelROI | None:
        import cv2

        frame_height, frame_width = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(
            gray,
            threshold1=self.config.canny_low,
            threshold2=self.config.canny_high,
        )
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(
            closed,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        frame_area = float(frame_width * frame_height)
        candidates: list[tuple[float, PanelROI]] = []
        for contour in contours:
            area = float(cv2.contourArea(contour))
            area_ratio = area / frame_area
            if area_ratio < self.config.min_area_ratio:
                continue
            perimeter = float(cv2.arcLength(contour, True))
            if perimeter <= 0.0:
                continue
            approx = cv2.approxPolyDP(
                contour,
                self.config.approx_epsilon_ratio * perimeter,
                True,
            )
            if len(approx) < 4 or len(approx) > 8:
                continue
            x, y, width, height = cv2.boundingRect(approx)
            if width < 2 or height < 2:
                continue
            aspect = max(width / height, height / width)
            if not self.config.min_aspect_ratio <= aspect <= self.config.max_aspect_ratio:
                continue
            rectangularity = area / float(width * height)
            if rectangularity < self.config.min_rectangularity:
                continue
            score = area_ratio * rectangularity
            candidates.append((score, PanelROI(x, y, width, height)))

        if not candidates:
            return None
        _, roi = max(candidates, key=lambda item: item[0])
        pad_x = int(round(roi.width * self.config.padding_ratio))
        pad_y = int(round(roi.height * self.config.padding_ratio))
        x = max(0, roi.x - pad_x)
        y = max(0, roi.y - pad_y)
        right = min(frame_width, roi.x + roi.width + pad_x)
        bottom = min(frame_height, roi.y + roi.height + pad_y)
        resolved = PanelROI(x, y, right - x, bottom - y)
        resolved.validate(frame_width, frame_height)
        return resolved
