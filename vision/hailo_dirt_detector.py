from __future__ import annotations

from typing import Any

from vision.dirt_detector_base import BBox, BaseDirtDetector, DirtDetectionResult


class HailoDirtDetector(BaseDirtDetector):
    """Reject the unavailable AI HAT path instead of silently changing models."""

    def __init__(self, detector_config: dict[str, Any]):
        model_path = detector_config.get("model_path")
        raise RuntimeError(
            "The Hailo/AI-HAT backend is unavailable in the final system. "
            "Run the CUDA ONNX laptop worker instead; "
            f"configured HEF={model_path!r}."
        )

    def detect(self, frame: Any, roi: BBox | None = None) -> DirtDetectionResult:
        raise RuntimeError("Hailo detection is unavailable; use laptop CUDA inference")
