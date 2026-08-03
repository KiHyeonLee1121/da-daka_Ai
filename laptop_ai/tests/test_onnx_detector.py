from pathlib import Path

import pytest
import numpy as np

from laptop_ai.config import DetectorConfig
from laptop_ai.onnx_detector import OnnxDetector
from laptop_ai.onnx_postprocess import postprocess_xyxy_score_class


def test_missing_onnx_model_path_has_clear_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing.onnx"
    with pytest.raises(FileNotFoundError, match="does not exist"):
        OnnxDetector(DetectorConfig(backend="onnx", model_path=str(missing)))


def test_model_specific_postprocess_isolated_from_runtime() -> None:
    output = np.array([[64, 64, 320, 320, 0.9, 0]], dtype=np.float32)
    candidate = postprocess_xyxy_score_class(
        output,
        image_width=640,
        image_height=480,
        input_width=640,
        input_height=640,
        confidence_threshold=0.5,
        class_id=0,
        coordinates_normalized=False,
    )
    assert candidate is not None
    assert candidate.bbox == pytest.approx((64, 48, 256, 192))
