"""ONNX Runtime detector with automatic CPU, CUDA, or DirectML execution."""

from __future__ import annotations

import logging
from pathlib import Path
import time

import numpy as np

from laptop_ai.config import DetectorConfig, PerformanceConfig
from laptop_ai.detection_types import DetectionResult
from laptop_ai.detector_base import BaseDetector
from laptop_ai.onnx_postprocess import postprocess_xyxy_score_class
from laptop_ai.performance import create_onnx_session_options
from laptop_ai.video_receiver import FramePacket


logger = logging.getLogger(__name__)


def select_onnx_providers(
    requested: str,
    available: list[str],
    *,
    device_id: int = 0,
) -> tuple[list[object], str, bool]:
    """Select a provider list and report whether CPU fallback was required."""
    if isinstance(device_id, bool) or not isinstance(device_id, int) or device_id < 0:
        raise ValueError("ONNX device_id must be a non-negative integer")
    normalized = requested.strip().lower()
    if normalized == "dml":
        normalized = "directml"
    supported = {"auto", "cpu", "cuda", "directml"}
    if normalized not in supported:
        raise ValueError(
            "detector.execution_provider must be auto, cpu, cuda, or directml"
        )

    available_set = set(available)
    selected = "CPUExecutionProvider"
    fallback = False
    if normalized == "auto":
        if "CUDAExecutionProvider" in available_set:
            selected = "CUDAExecutionProvider"
        elif "DmlExecutionProvider" in available_set:
            selected = "DmlExecutionProvider"
    elif normalized == "cuda":
        if "CUDAExecutionProvider" in available_set:
            selected = "CUDAExecutionProvider"
        else:
            fallback = True
    elif normalized == "directml":
        if "DmlExecutionProvider" in available_set:
            selected = "DmlExecutionProvider"
        else:
            fallback = True

    if selected == "CPUExecutionProvider" and selected not in available_set:
        raise RuntimeError(
            "CPUExecutionProvider is unavailable and no requested GPU provider exists"
        )
    if selected == "CPUExecutionProvider":
        return [selected], selected, fallback
    provider_options = {"device_id": str(device_id)}
    providers: list[object] = [(selected, provider_options)]
    if "CPUExecutionProvider" in available_set:
        providers.append("CPUExecutionProvider")
    return providers, selected, fallback


class OnnxDetector(BaseDetector):
    def __init__(
        self,
        config: DetectorConfig,
        performance: PerformanceConfig | None = None,
    ) -> None:
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
                "onnxruntime is required for detector.backend=onnx; install "
                "requirements.txt, requirements-directml.txt, or "
                "requirements-cuda.txt"
            ) from exc

        available = ort.get_available_providers()
        performance_config = performance or PerformanceConfig()
        providers, selected_provider, fallback = select_onnx_providers(
            config.execution_provider,
            available,
            device_id=performance_config.onnx_device_id,
        )
        if fallback:
            logger.warning(
                "requested ONNX provider %s unavailable; using CPUExecutionProvider",
                config.execution_provider,
            )

        self.config = config
        self.model_path = model_path
        self.model_name = model_path.name
        session_options = create_onnx_session_options(
            ort,
            performance_config,
            execution_provider=selected_provider,
        )
        self._session = ort.InferenceSession(
            str(model_path),
            sess_options=session_options,
            providers=providers,
        )
        logger.info(
            "ONNX runtime model=%s requested_provider=%s selected_provider=%s "
            "providers=%s device_id=%d intra_threads=%s inter_threads=%s "
            "execution=%s graph_optimization=%s",
            model_path,
            config.execution_provider,
            selected_provider,
            self._session.get_providers(),
            performance_config.onnx_device_id,
            performance_config.onnx_intra_op_threads or "auto",
            performance_config.onnx_inter_op_threads or "auto",
            (
                "sequential"
                if selected_provider == "DmlExecutionProvider"
                else performance_config.onnx_execution_mode
            ),
            performance_config.onnx_graph_optimization,
        )
        inputs = self._session.get_inputs()
        if len(inputs) != 1:
            raise ValueError(f"ONNX detector expects one input, model has {len(inputs)}")
        self._input_name = inputs[0].name

    @property
    def execution_providers(self) -> tuple[str, ...]:
        """Return the active ONNX Runtime providers in priority order."""
        return tuple(self._session.get_providers())

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
