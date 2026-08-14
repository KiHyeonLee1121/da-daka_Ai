"""Panel ROI -> dirt detector pipeline with full-frame coordinate remapping."""

from __future__ import annotations

from dataclasses import replace
import time

from laptop_ai.detection_types import DetectionResult
from laptop_ai.detector_base import BaseDetector
from laptop_ai.panel_detector import PanelDetector, PanelROI
from laptop_ai.video_receiver import FramePacket


class PanelDirtPipeline:
    """Run dirt inference only inside a confirmed panel ROI.

    The output contract remains the existing full-frame normalized
    DetectionResult, so Raspberry Pi control does not need to know which panel
    detector or AI model produced the coordinates.
    """

    def __init__(self, panel_detector: PanelDetector, dirt_detector: BaseDetector) -> None:
        self.panel_detector = panel_detector
        self.dirt_detector = dirt_detector
        self.last_panel_roi: PanelROI | None = None

    def detect(self, packet: FramePacket) -> DetectionResult:
        roi = self.panel_detector.detect(packet.frame)
        self.last_panel_roi = roi
        if roi is None:
            now_ns = time.time_ns()
            return DetectionResult.no_detection(
                frame_id=packet.frame_id,
                capture_timestamp_ns=packet.capture_timestamp_ns,
                inference_timestamp_ns=max(now_ns, packet.capture_timestamp_ns),
                image_width=packet.image_width,
                image_height=packet.image_height,
                inference_time_ms=0.0,
                model_name="panel-not-found",
            )

        roi.validate(packet.image_width, packet.image_height)
        crop = packet.frame[
            roi.y : roi.y + roi.height,
            roi.x : roi.x + roi.width,
        ]
        crop_packet = FramePacket(
            frame_id=packet.frame_id,
            capture_timestamp_ns=packet.capture_timestamp_ns,
            received_monotonic_ns=packet.received_monotonic_ns,
            image_width=roi.width,
            image_height=roi.height,
            frame=crop,
        )
        crop_result = self.dirt_detector.detect(crop_packet)
        if not crop_result.dirt_found:
            return DetectionResult.no_detection(
                frame_id=crop_result.frame_id,
                capture_timestamp_ns=crop_result.capture_timestamp_ns,
                inference_timestamp_ns=crop_result.inference_timestamp_ns,
                image_width=packet.image_width,
                image_height=packet.image_height,
                inference_time_ms=crop_result.inference_time_ms,
                model_name=crop_result.model_name,
            )

        full_width = float(packet.image_width)
        full_height = float(packet.image_height)
        roi_width = float(roi.width)
        roi_height = float(roi.height)
        centroid_x = (roi.x + crop_result.centroid_x_norm * roi_width) / full_width
        centroid_y = (roi.y + crop_result.centroid_y_norm * roi_height) / full_height
        bbox_x = (roi.x + crop_result.bbox_x_norm * roi_width) / full_width
        bbox_y = (roi.y + crop_result.bbox_y_norm * roi_height) / full_height
        bbox_w = crop_result.bbox_w_norm * roi_width / full_width
        bbox_h = crop_result.bbox_h_norm * roi_height / full_height
        area_ratio = (
            crop_result.area_ratio
            * roi_width
            * roi_height
            / (full_width * full_height)
        )
        return replace(
            crop_result,
            image_width=packet.image_width,
            image_height=packet.image_height,
            centroid_x_norm=centroid_x,
            centroid_y_norm=centroid_y,
            bbox_x_norm=bbox_x,
            bbox_y_norm=bbox_y,
            bbox_w_norm=bbox_w,
            bbox_h_norm=bbox_h,
            area_ratio=area_ratio,
        )

    def close(self) -> None:
        self.dirt_detector.close()
