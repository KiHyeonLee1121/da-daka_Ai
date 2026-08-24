from __future__ import annotations

from typing import Any

from vision.dirt_detector_base import BBox, BaseDirtDetector, DirtDetectionResult


class HailoDirtDetector(BaseDirtDetector):
    """Reject an uncompiled/unvalidated HEF instead of silently changing models."""

    def __init__(self, detector_config: dict[str, Any]):
        model_path = detector_config.get("model_path")
        raise RuntimeError(
            "The Hailo/AI-HAT backend is not yet compiled and hardware-validated. "
            "Use the manifest-validated CUDA ONNX laptop worker until an equivalent "
            "HEF passes calibration-set accuracy and Pi latency gates; "
            f"configured HEF={model_path!r}."
        )

    def detect(self, frame: Any, roi: BBox | None = None) -> DirtDetectionResult:
        raise RuntimeError(
            "Hailo detection is fail-closed until a validated HEF adapter is deployed"
        )
