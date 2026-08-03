"""Inspectable OpenCV detector adapted from vision/opencv_dirt_detector.py."""

from __future__ import annotations

import math
import time
from typing import Any

import numpy as np

from laptop_ai.config import DetectorConfig
from laptop_ai.detection_types import DetectionResult
from laptop_ai.detector_base import BaseDetector
from laptop_ai.video_receiver import FramePacket


class OpenCvDetector(BaseDetector):
    model_name = "opencv-mvp"

    def __init__(self, config: DetectorConfig) -> None:
        self.config = config

    def detect(self, packet: FramePacket) -> DetectionResult:
        import cv2

        started = time.perf_counter_ns()
        frame = packet.frame
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        median = float(np.median(blurred))
        deviation = float(np.std(blurred))
        contrast_floor = max(15.0, 0.7 * deviation)
        bright_cut = int(min(255, max(120, median + contrast_floor)))
        dark_cut = int(max(0, min(135, median - contrast_floor)))
        bright_mask = cv2.inRange(blurred, bright_cut, 255)
        dark_mask = cv2.inRange(blurred, 0, dark_cut)
        if self.config.threshold_mode == "adaptive":
            adaptive_bright = cv2.adaptiveThreshold(
                blurred,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                35,
                -5,
            )
            adaptive_dark = cv2.adaptiveThreshold(
                blurred,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV,
                35,
                5,
            )
            bright_mask = cv2.bitwise_or(bright_mask, adaptive_bright)
            dark_mask = cv2.bitwise_or(dark_mask, adaptive_dark)
        elif self.config.threshold_mode == "otsu":
            _, bright_mask = cv2.threshold(
                blurred,
                0,
                255,
                cv2.THRESH_BINARY + cv2.THRESH_OTSU,
            )
            _, dark_mask = cv2.threshold(
                blurred,
                0,
                255,
                cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
            )
        masks = [bright_mask, dark_mask]
        kernel = np.ones((3, 3), np.uint8)
        candidates: list[
            tuple[float, tuple[int, int], tuple[int, int, int, int], float, float]
        ] = []
        frame_area = float(max(1, packet.image_width * packet.image_height))
        max_center_distance = math.hypot(packet.image_width / 2.0, packet.image_height / 2.0)

        for mask in masks:
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area = float(cv2.contourArea(contour))
                if area < self.config.min_area or area > self.config.max_area:
                    continue
                x, y, width, height = cv2.boundingRect(contour)
                pad = self.config.ignore_border_px
                if pad > 0 and (
                    x <= pad
                    or y <= pad
                    or x + width >= packet.image_width - pad
                    or y + height >= packet.image_height - pad
                ):
                    continue
                moments = cv2.moments(contour)
                if moments["m00"] == 0:
                    continue
                cx = int(moments["m10"] / moments["m00"])
                cy = int(moments["m01"] / moments["m00"])
                contour_mask = np.zeros(gray.shape, dtype=np.uint8)
                cv2.drawContours(contour_mask, [contour], -1, 255, thickness=-1)
                if self._is_specular(contour_mask, hsv):
                    continue
                mean_inside = float(cv2.mean(blurred, mask=contour_mask)[0])
                contrast = abs(mean_inside - median) / 255.0
                area_score = min(1.0, area / max(self.config.min_area * 10.0, 1.0))
                confidence = min(1.0, 0.2 + 1.5 * contrast + 0.25 * area_score)
                if confidence < self.config.confidence_threshold:
                    continue
                norm_area = min(1.0, area / max(frame_area * 0.05, 1.0))
                distance = math.hypot(
                    cx - packet.image_width / 2.0,
                    cy - packet.image_height / 2.0,
                ) / max(max_center_distance, 1.0)
                score = (
                    self.config.priority_w_area * norm_area
                    - self.config.priority_w_dist * distance
                    + self.config.priority_w_conf * confidence
                )
                candidates.append((score, (cx, cy), (x, y, width, height), area, confidence))

        inference_timestamp_ns = time.time_ns()
        inference_ms = (time.perf_counter_ns() - started) / 1e6
        if not candidates:
            return DetectionResult.no_detection(
                frame_id=packet.frame_id,
                capture_timestamp_ns=packet.capture_timestamp_ns,
                inference_timestamp_ns=inference_timestamp_ns,
                image_width=packet.image_width,
                image_height=packet.image_height,
                inference_time_ms=inference_ms,
                model_name=self.model_name,
            )
        _, centroid, bbox, area, confidence = max(candidates, key=lambda item: item[0])
        return DetectionResult.from_pixel_detection(
            frame_id=packet.frame_id,
            capture_timestamp_ns=packet.capture_timestamp_ns,
            inference_timestamp_ns=inference_timestamp_ns,
            image_width=packet.image_width,
            image_height=packet.image_height,
            centroid=centroid,
            bbox=bbox,
            area=area,
            confidence=confidence,
            inference_time_ms=inference_ms,
            model_name=self.model_name,
        )

    def _is_specular(self, contour_mask: Any, hsv: Any) -> bool:
        if not self.config.reject_specular_highlights:
            return False
        selected = contour_mask > 0
        if not np.any(selected):
            return False
        saturation_mean = float(np.mean(hsv[:, :, 1][selected]))
        value_p90 = float(np.percentile(hsv[:, :, 2][selected], 90))
        return (
            value_p90 >= self.config.specular_v_threshold
            and saturation_mean <= self.config.specular_saturation_max
        )
