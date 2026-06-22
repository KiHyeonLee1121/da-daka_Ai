from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from vision.opencv_dirt_detector import OpenCVDirtDetector


def test_synthetic_blob_detected_with_centroid() -> None:
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    cv2.circle(frame, (120, 80), 20, (180, 180, 180), -1)

    detector = OpenCVDirtDetector(
        {
            "min_area": 50,
            "max_area": 10000,
            "threshold_mode": "adaptive",
            "confidence_threshold": 0.2,
        }
    )
    result = detector.detect(frame)

    assert result.found is True
    assert result.centroid is not None
    cx, cy = result.centroid
    assert abs(cx - 120) <= 5
    assert abs(cy - 80) <= 5
    assert result.area > 500
