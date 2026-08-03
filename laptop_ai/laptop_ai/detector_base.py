"""Detector interface shared by OpenCV and ONNX backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from laptop_ai.detection_types import DetectionResult
from laptop_ai.video_receiver import FramePacket


class BaseDetector(ABC):
    @abstractmethod
    def detect(self, packet: FramePacket) -> DetectionResult:
        """Run inference and return one normalized result for the frame."""

    def close(self) -> None:
        """Release optional backend resources."""
