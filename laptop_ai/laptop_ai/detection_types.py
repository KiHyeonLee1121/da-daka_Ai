"""Common normalized detection result used by every detector backend."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import math
from typing import Any


PROTOCOL_VERSION = 1


@dataclass(frozen=True, slots=True)
class DetectionResult:
    protocol_version: int
    source_id: str
    session_id: str
    frame_id: int
    capture_timestamp_ns: int
    inference_timestamp_ns: int
    send_timestamp_ns: int
    image_width: int
    image_height: int
    dirt_found: bool
    centroid_x_norm: float
    centroid_y_norm: float
    bbox_x_norm: float
    bbox_y_norm: float
    bbox_w_norm: float
    bbox_h_norm: float
    area_ratio: float
    confidence: float
    inference_time_ms: float
    model_name: str
    sequence: int

    @classmethod
    def no_detection(
        cls,
        *,
        frame_id: int,
        capture_timestamp_ns: int,
        inference_timestamp_ns: int,
        image_width: int,
        image_height: int,
        inference_time_ms: float,
        model_name: str,
    ) -> "DetectionResult":
        return cls(
            protocol_version=PROTOCOL_VERSION,
            source_id="",
            session_id="",
            frame_id=frame_id,
            capture_timestamp_ns=capture_timestamp_ns,
            inference_timestamp_ns=inference_timestamp_ns,
            send_timestamp_ns=0,
            image_width=image_width,
            image_height=image_height,
            dirt_found=False,
            centroid_x_norm=0.0,
            centroid_y_norm=0.0,
            bbox_x_norm=0.0,
            bbox_y_norm=0.0,
            bbox_w_norm=0.0,
            bbox_h_norm=0.0,
            area_ratio=0.0,
            confidence=0.0,
            inference_time_ms=inference_time_ms,
            model_name=model_name,
            sequence=0,
        )

    @classmethod
    def from_pixel_detection(
        cls,
        *,
        frame_id: int,
        capture_timestamp_ns: int,
        inference_timestamp_ns: int,
        image_width: int,
        image_height: int,
        centroid: tuple[float, float],
        bbox: tuple[float, float, float, float],
        area: float,
        confidence: float,
        inference_time_ms: float,
        model_name: str,
    ) -> "DetectionResult":
        if image_width <= 0 or image_height <= 0:
            raise ValueError("image dimensions must be positive")
        x, y, width, height = bbox
        return cls(
            protocol_version=PROTOCOL_VERSION,
            source_id="",
            session_id="",
            frame_id=frame_id,
            capture_timestamp_ns=capture_timestamp_ns,
            inference_timestamp_ns=inference_timestamp_ns,
            send_timestamp_ns=0,
            image_width=image_width,
            image_height=image_height,
            dirt_found=True,
            centroid_x_norm=float(centroid[0]) / image_width,
            centroid_y_norm=float(centroid[1]) / image_height,
            bbox_x_norm=float(x) / image_width,
            bbox_y_norm=float(y) / image_height,
            bbox_w_norm=float(width) / image_width,
            bbox_h_norm=float(height) / image_height,
            area_ratio=float(area) / float(image_width * image_height),
            confidence=float(confidence),
            inference_time_ms=float(inference_time_ms),
            model_name=model_name,
            sequence=0,
        )

    def with_transport(
        self,
        *,
        source_id: str,
        session_id: str,
        sequence: int,
        send_timestamp_ns: int,
    ) -> "DetectionResult":
        return replace(
            self,
            source_id=source_id,
            session_id=session_id,
            sequence=sequence,
            send_timestamp_ns=send_timestamp_ns,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self, *, require_transport: bool = True) -> None:
        """Reject values that are unsafe or invalid for JSON transport."""
        if (
            isinstance(self.protocol_version, bool)
            or not isinstance(self.protocol_version, int)
            or self.protocol_version != PROTOCOL_VERSION
        ):
            raise ValueError(f"unsupported protocol version: {self.protocol_version}")
        if not isinstance(self.source_id, str) or not isinstance(self.session_id, str):
            raise ValueError("source_id and session_id must be strings")
        if require_transport and (not self.source_id or not self.session_id):
            raise ValueError("source_id and session_id are required")
        if not isinstance(self.model_name, str) or not self.model_name:
            raise ValueError("model_name must be a non-empty string")
        if not isinstance(self.dirt_found, bool):
            raise ValueError("dirt_found must be boolean")
        integers = {
            "frame_id": self.frame_id,
            "capture_timestamp_ns": self.capture_timestamp_ns,
            "inference_timestamp_ns": self.inference_timestamp_ns,
            "send_timestamp_ns": self.send_timestamp_ns,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "sequence": self.sequence,
        }
        for name, value in integers.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.image_width <= 0 or self.image_height <= 0:
            raise ValueError("image dimensions must be positive")
        if self.inference_timestamp_ns < self.capture_timestamp_ns:
            raise ValueError("inference timestamp cannot precede capture timestamp")
        if require_transport and self.send_timestamp_ns < self.inference_timestamp_ns:
            raise ValueError("send timestamp cannot precede inference timestamp")

        floats = {
            "centroid_x_norm": self.centroid_x_norm,
            "centroid_y_norm": self.centroid_y_norm,
            "bbox_x_norm": self.bbox_x_norm,
            "bbox_y_norm": self.bbox_y_norm,
            "bbox_w_norm": self.bbox_w_norm,
            "bbox_h_norm": self.bbox_h_norm,
            "area_ratio": self.area_ratio,
            "confidence": self.confidence,
            "inference_time_ms": self.inference_time_ms,
        }
        for name, value in floats.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        for name in (
            "centroid_x_norm",
            "centroid_y_norm",
            "bbox_x_norm",
            "bbox_y_norm",
            "bbox_w_norm",
            "bbox_h_norm",
            "area_ratio",
            "confidence",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be within [0, 1]")
        if self.bbox_x_norm + self.bbox_w_norm > 1.0 + 1e-6:
            raise ValueError("normalized bbox exceeds image width")
        if self.bbox_y_norm + self.bbox_h_norm > 1.0 + 1e-6:
            raise ValueError("normalized bbox exceeds image height")
        if self.inference_time_ms < 0.0:
            raise ValueError("inference_time_ms cannot be negative")
        if self.dirt_found:
            if self.bbox_w_norm <= 0.0 or self.bbox_h_norm <= 0.0:
                raise ValueError("a detection requires a non-empty bbox")
            if self.confidence <= 0.0:
                raise ValueError("a detection requires positive confidence")
        else:
            zero_fields = (
                self.centroid_x_norm,
                self.centroid_y_norm,
                self.bbox_x_norm,
                self.bbox_y_norm,
                self.bbox_w_norm,
                self.bbox_h_norm,
                self.area_ratio,
                self.confidence,
            )
            if any(value != 0.0 for value in zero_fields):
                raise ValueError("no-detection messages must use zero detection values")
