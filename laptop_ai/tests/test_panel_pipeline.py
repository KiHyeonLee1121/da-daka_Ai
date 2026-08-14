from __future__ import annotations

import numpy as np
import pytest

from laptop_ai.config import PanelConfig
from laptop_ai.detection_types import DetectionResult
from laptop_ai.detector_base import BaseDetector
from laptop_ai.panel_detector import PanelDetector
from laptop_ai.perception_pipeline import PanelDirtPipeline
from laptop_ai.video_receiver import FramePacket


class _CenterDetector(BaseDetector):
    def detect(self, packet: FramePacket) -> DetectionResult:
        return DetectionResult.from_pixel_detection(
            frame_id=packet.frame_id,
            capture_timestamp_ns=packet.capture_timestamp_ns,
            inference_timestamp_ns=packet.capture_timestamp_ns + 1,
            image_width=packet.image_width,
            image_height=packet.image_height,
            centroid=(packet.image_width / 2.0, packet.image_height / 2.0),
            bbox=(10.0, 10.0, 20.0, 20.0),
            area=400.0,
            confidence=0.9,
            inference_time_ms=2.0,
            model_name="dummy",
        )


def _packet() -> FramePacket:
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    return FramePacket(
        frame_id=7,
        capture_timestamp_ns=100,
        received_monotonic_ns=100,
        image_width=640,
        image_height=480,
        frame=frame,
    )


def test_manual_panel_roi_remaps_dirt_to_full_frame_coordinates() -> None:
    panel = PanelDetector(
        PanelConfig(
            mode="manual",
            manual_x=160,
            manual_y=120,
            manual_width=320,
            manual_height=240,
        )
    )
    pipeline = PanelDirtPipeline(panel, _CenterDetector())
    result = pipeline.detect(_packet())

    assert result.dirt_found
    assert result.image_width == 640
    assert result.image_height == 480
    assert result.centroid_x_norm == pytest.approx(0.5)
    assert result.centroid_y_norm == pytest.approx(0.5)
    assert result.bbox_x_norm == pytest.approx((160 + 10) / 640)
    assert result.bbox_y_norm == pytest.approx((120 + 10) / 480)
    assert result.bbox_w_norm == pytest.approx(20 / 640)
    assert result.bbox_h_norm == pytest.approx(20 / 480)
    result.validate(require_transport=False)


def test_full_frame_panel_keeps_detector_coordinates_unchanged() -> None:
    pipeline = PanelDirtPipeline(
        PanelDetector(PanelConfig(mode="full_frame")),
        _CenterDetector(),
    )
    result = pipeline.detect(_packet())
    assert result.centroid_x_norm == pytest.approx(0.5)
    assert result.centroid_y_norm == pytest.approx(0.5)
    assert result.bbox_x_norm == pytest.approx(10 / 640)
    assert result.bbox_y_norm == pytest.approx(10 / 480)
