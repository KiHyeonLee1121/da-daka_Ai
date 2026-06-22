from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from vision.opencv_dirt_detector import OpenCVDirtDetector


def test_specular_highlight_on_acrylic_is_rejected() -> None:
    frame = np.full((240, 320, 3), 30, dtype=np.uint8)
    cv2.circle(frame, (160, 120), 18, (255, 255, 255), -1)

    detector = OpenCVDirtDetector(
        {
            "min_area": 50,
            "max_area": 10000,
            "threshold_mode": "adaptive",
            "confidence_threshold": 0.2,
            "reject_specular_highlights": True,
            "specular_v_threshold": 245,
            "specular_saturation_max": 45,
        }
    )

    result = detector.detect(frame)
    assert result.found is False
