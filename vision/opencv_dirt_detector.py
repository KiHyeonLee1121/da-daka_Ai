from __future__ import annotations

import math
from typing import Any

import numpy as np

from vision.dirt_detector_base import BBox, BaseDirtDetector, DirtCandidate, DirtDetectionResult


class OpenCVDirtDetector(BaseDirtDetector):
    """OpenCV based dirt detector for the MVP.

    The detector intentionally favors robust, inspectable image processing over
    model accuracy. Bright and dark blobs are processed separately so large
    panel backgrounds do not merge with actual dirt candidates.
    """

    def __init__(self, detector_config: dict[str, Any]):
        self.min_area = float(detector_config.get("min_area", 80))
        self.max_area = float(detector_config.get("max_area", 50000))
        self.threshold_mode = str(detector_config.get("threshold_mode", "adaptive"))
        self.confidence_threshold = float(detector_config.get("confidence_threshold", 0.3))
        self.reject_specular_highlights = bool(detector_config.get("reject_specular_highlights", True))
        self.specular_v_threshold = float(detector_config.get("specular_v_threshold", 245))
        self.specular_saturation_max = float(detector_config.get("specular_saturation_max", 45))
        self.ignore_border_px = int(detector_config.get("ignore_border_px", 0))
        self.w_area = float(detector_config.get("priority_w_area", 0.45))
        self.w_dist = float(detector_config.get("priority_w_dist", 0.25))
        self.w_conf = float(detector_config.get("priority_w_conf", 0.30))

    def detect(self, frame: Any, roi: BBox | None = None) -> DirtDetectionResult:
        import cv2

        height, width = frame.shape[:2]
        x, y, w, h = roi if roi is not None else (0, 0, width, height)
        x, y, w, h = self._clip_roi(x, y, w, h, width, height)
        roi_frame = frame[y : y + h, x : x + w]

        if roi_frame.size == 0:
            return DirtDetectionResult.empty()

        gray = cv2.cvtColor(roi_frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        hsv = cv2.cvtColor(roi_frame, cv2.COLOR_BGR2HSV)
        bright_mask, dark_mask = self._build_masks(gray)

        full_mask = np.zeros((height, width), dtype=np.uint8)
        candidates: list[DirtCandidate] = []
        for mask in (bright_mask, dark_mask):
            candidates.extend(
                self._candidates_from_mask(
                    mask=mask,
                    gray=gray,
                    hsv=hsv,
                    offset=(x, y),
                    frame_size=(width, height),
                    roi_size=(w, h),
                    full_mask=full_mask,
                )
            )

        if not candidates:
            return DirtDetectionResult.empty(mask=full_mask)

        candidates.sort(key=lambda c: c.score, reverse=True)
        best = candidates[0]
        return DirtDetectionResult(
            found=True,
            centroid=best.centroid,
            bbox=best.bbox,
            area=best.area,
            confidence=best.confidence,
            mask=full_mask,
            candidates=candidates,
        )

    def _build_masks(self, gray: Any) -> tuple[Any, Any]:
        import cv2

        median = float(np.median(gray))
        std = float(np.std(gray))
        contrast_floor = max(15.0, 0.7 * std)
        bright_cut = int(min(255, max(120, median + contrast_floor)))
        dark_cut = int(max(0, min(135, median - contrast_floor)))

        bright_mask = cv2.inRange(gray, bright_cut, 255)
        dark_mask = cv2.inRange(gray, 0, dark_cut)

        if self.threshold_mode == "adaptive":
            block = 35
            adaptive_bright = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, -5
            )
            adaptive_dark = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, block, 5
            )
            bright_mask = cv2.bitwise_or(bright_mask, adaptive_bright)
            dark_mask = cv2.bitwise_or(dark_mask, adaptive_dark)
        elif self.threshold_mode == "otsu":
            _, bright_mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            _, dark_mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        kernel = np.ones((3, 3), np.uint8)
        bright_mask = cv2.morphologyEx(bright_mask, cv2.MORPH_OPEN, kernel, iterations=1)
        bright_mask = cv2.morphologyEx(bright_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        dark_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_OPEN, kernel, iterations=1)
        dark_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        return bright_mask, dark_mask

    def _candidates_from_mask(
        self,
        mask: Any,
        gray: Any,
        hsv: Any,
        offset: tuple[int, int],
        frame_size: tuple[int, int],
        roi_size: tuple[int, int],
        full_mask: Any,
    ) -> list[DirtCandidate]:
        import cv2

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        frame_w, frame_h = frame_size
        roi_w, roi_h = roi_size
        roi_area = max(1.0, float(roi_w * roi_h))
        center_x = frame_w / 2.0
        center_y = frame_h / 2.0
        max_center_distance = math.hypot(center_x, center_y)
        global_median = float(np.median(gray))
        out: list[DirtCandidate] = []

        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < self.min_area or area > self.max_area:
                continue

            x, y, w, h = cv2.boundingRect(contour)
            if self._touches_ignored_border(x, y, w, h, roi_w, roi_h):
                continue

            moments = cv2.moments(contour)
            if moments["m00"] == 0:
                continue

            local_cx = int(moments["m10"] / moments["m00"])
            local_cy = int(moments["m01"] / moments["m00"])
            cx = local_cx + offset[0]
            cy = local_cy + offset[1]
            bbox = (x + offset[0], y + offset[1], w, h)

            contour_mask = np.zeros(gray.shape, dtype=np.uint8)
            cv2.drawContours(contour_mask, [contour], -1, 255, thickness=-1)
            mean_inside = float(cv2.mean(gray, mask=contour_mask)[0])
            if self._is_specular_highlight(contour_mask, hsv):
                continue

            contrast = abs(mean_inside - global_median) / 255.0
            area_score = min(1.0, area / max(self.min_area * 10.0, 1.0))
            confidence = min(1.0, 0.2 + 1.5 * contrast + 0.25 * area_score)
            if confidence < self.confidence_threshold:
                continue

            norm_area = min(1.0, area / max(roi_area * 0.05, 1.0))
            norm_distance = min(1.0, math.hypot(cx - center_x, cy - center_y) / max_center_distance)
            score = self.w_area * norm_area - self.w_dist * norm_distance + self.w_conf * confidence

            shifted_contour = contour + np.array([[[offset[0], offset[1]]]], dtype=contour.dtype)
            cv2.drawContours(full_mask, [shifted_contour], -1, 255, thickness=-1)
            out.append(
                DirtCandidate(
                    centroid=(int(cx), int(cy)),
                    bbox=bbox,
                    area=area,
                    confidence=confidence,
                    score=score,
                )
            )

        return out

    def _touches_ignored_border(self, x: int, y: int, w: int, h: int, roi_w: int, roi_h: int) -> bool:
        if self.ignore_border_px <= 0:
            return False
        pad = self.ignore_border_px
        return x <= pad or y <= pad or x + w >= roi_w - pad or y + h >= roi_h - pad

    def _is_specular_highlight(self, contour_mask: Any, hsv: Any) -> bool:
        if not self.reject_specular_highlights:
            return False
        masked = contour_mask > 0
        if not np.any(masked):
            return False
        saturation_mean = float(np.mean(hsv[:, :, 1][masked]))
        value_p90 = float(np.percentile(hsv[:, :, 2][masked], 90))
        return value_p90 >= self.specular_v_threshold and saturation_mean <= self.specular_saturation_max

    @staticmethod
    def _clip_roi(x: int, y: int, w: int, h: int, frame_w: int, frame_h: int) -> BBox:
        x = max(0, min(int(x), frame_w - 1))
        y = max(0, min(int(y), frame_h - 1))
        w = max(1, min(int(w), frame_w - x))
        h = max(1, min(int(h), frame_h - y))
        return x, y, w, h
