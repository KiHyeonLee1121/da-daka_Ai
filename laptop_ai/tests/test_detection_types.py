from dataclasses import replace
import math

import pytest

from laptop_ai.detection_types import DetectionResult


def detected_result() -> DetectionResult:
    return DetectionResult.from_pixel_detection(
        frame_id=10,
        capture_timestamp_ns=100,
        inference_timestamp_ns=200,
        image_width=640,
        image_height=480,
        centroid=(320, 120),
        bbox=(256, 96, 128, 72),
        area=9216,
        confidence=0.9,
        inference_time_ms=12.5,
        model_name="test-model",
    )


def test_pixel_values_are_normalized() -> None:
    result = detected_result()
    result.validate(require_transport=False)
    assert result.centroid_x_norm == pytest.approx(0.5)
    assert result.centroid_y_norm == pytest.approx(0.25)
    assert result.bbox_w_norm == pytest.approx(0.2)
    assert result.bbox_h_norm == pytest.approx(0.15)


@pytest.mark.parametrize(
    "bad_result",
    [
        replace(detected_result(), confidence=math.nan),
        replace(detected_result(), bbox_x_norm=0.9, bbox_w_norm=0.2),
        replace(detected_result(), centroid_x_norm=-0.1),
    ],
)
def test_non_finite_and_out_of_range_values_are_rejected(
    bad_result: DetectionResult,
) -> None:
    with pytest.raises(ValueError):
        bad_result.validate(require_transport=False)
