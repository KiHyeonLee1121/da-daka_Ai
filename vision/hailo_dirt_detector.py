from __future__ import annotations

import logging
from typing import Any

from vision.dirt_detector_base import BBox, BaseDirtDetector, DirtDetectionResult
from vision.opencv_dirt_detector import OpenCVDirtDetector

logger = logging.getLogger(__name__)


class HailoDirtDetector(BaseDirtDetector):
    """AI HAT+ detector placeholder.

    A Hailo HEF model is not included in the MVP, so this class preserves the
    backend interface and safely falls back to OpenCV while logging the reason.
    Later, replace `detect()` with HailoRT preprocessing/inference/postprocess.
    """

    def __init__(self, detector_config: dict[str, Any]):
        self.model_path = detector_config.get("model_path")
        self._fallback = OpenCVDirtDetector(detector_config)
        self._warned = False

    def detect(self, frame: Any, roi: BBox | None = None) -> DirtDetectionResult:
        if not self._warned:
            logger.warning(
                "Hailo detector selected, but no HEF inference pipeline is implemented yet. "
                "Using OpenCV fallback. model_path=%s",
                self.model_path,
            )
            self._warned = True
        return self._fallback.detect(frame, roi)
