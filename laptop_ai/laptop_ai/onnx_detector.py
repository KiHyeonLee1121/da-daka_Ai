"""ONNX Runtime detector with configurable CPU or CUDA execution."""

from __future__ import annotations

import logging
from pathlib import Path
import time

import numpy as np

from laptop_ai.config import DetectorConfig
from laptop_ai.detection_types import DetectionResult
from laptop_ai.detector_base import BaseDetector
from laptop_ai.onnx_postprocess import postprocess_xyxy_score_class
from laptop_ai.video_receiver import FramePacket


logger = logging.getLogger(__name__)


class OnnxDetector(BaseDetector):
    def __init__(self, config: DetectorConfig) -> None:
        if not config.model_path:
            raise ValueError("detector.model_path is required for the ONNX backend")
        model_path = Path(config.model_path).expanduser()
        if not model_path.is_file():
            raise FileNotFoundError(f"ONNX model file does not exist: {model_path}")
        if config.output_format != "xyxy_score_class":
            raise ValueError(
                "only detector.output_format=xyxy_score_class is currently implemented"
            )
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError(
                "onnxruntime is required for detector.backend=onnx; "
                "install laptop_ai/requirements.txt"
            ) from exc

        available = ort.get_available_providers()
        requested = config.execution_provider.lower()
        if requested == "cuda" and "CUDAExecutionProvider" in available:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        elif requested == "cuda":
            logger.warning("CUDAExecutionProvider unavailable; using CPUExecutionProvider")
            providers = ["CPUExecutionProvider"]
        elif requested == "cpu":
            providers = ["CPUExecutionProvider"]
        else:
            raise ValueError("detector.execution_provider must be 'cpu' or 'cuda'")

        self.config = config
        self.model_path = model_path
        self.model_name = model_path.name
        self._session = ort.InferenceSession(str(model_path), providers=providers)
        inputs = self._session.get_inputs()
        if len(inputs) != 1:
            raise ValueError(f"ONNX detector expects one input, model has {len(inputs)}")
        self._input_name = inputs[0].name

    def detect(self, packet: FramePacket) -> DetectionResult:
        import cv2

        started = time.perf_counter_ns()
        resized = cv2.resize(
            packet.frame,
            (self.config.input_width, self.config.input_height),
        )
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        tensor = np.transpose(rgb.astype(np.float32) / 255.0, (2, 0, 1))[None, ...]
        outputs = self._session.run(None, {self._input_name: tensor})
        if not outputs:
            raise ValueError("ONNX model returned no outputs")
        candidate = postprocess_xyxy_score_class(
            outputs[0],
            image_width=packet.image_width,
            image_height=packet.image_height,
            input_width=self.config.input_width,
            input_height=self.config.input_height,
            confidence_threshold=self.config.confidence_threshold,
            class_id=self.config.class_id,
            coordinates_normalized=self.config.coordinates_normalized,
        )
        inference_timestamp_ns = time.time_ns()
        inference_ms = (time.perf_counter_ns() - started) / 1e6
        if candidate is None:
            return DetectionResult.no_detection(
                frame_id=packet.frame_id,
                capture_timestamp_ns=packet.capture_timestamp_ns,
                inference_timestamp_ns=inference_timestamp_ns,
                image_width=packet.image_width,
                image_height=packet.image_height,
                inference_time_ms=inference_ms,
                model_name=self.model_name,
            )
        return DetectionResult.from_pixel_detection(
            frame_id=packet.frame_id,
            capture_timestamp_ns=packet.capture_timestamp_ns,
            inference_timestamp_ns=inference_timestamp_ns,
            image_width=packet.image_width,
            image_height=packet.image_height,
            centroid=candidate.centroid,
            bbox=candidate.bbox,
            area=candidate.area,
            confidence=candidate.confidence,
            inference_time_ms=inference_ms,
            model_name=self.model_name,
        )
