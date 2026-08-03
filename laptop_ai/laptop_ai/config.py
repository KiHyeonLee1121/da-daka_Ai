"""Typed configuration loading for the laptop AI process."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class VideoConfig:
    source: str | int
    backend: str = "opencv"
    reconnect_interval_s: float = 2.0
    max_consecutive_failures: int = 30
    frame_width: int = 640
    frame_height: int = 480
    process_every_n_frames: int = 1
    max_frame_age_s: float = 0.5


@dataclass(frozen=True, slots=True)
class DetectorConfig:
    backend: str = "opencv"
    confidence_threshold: float = 0.5
    model_path: str | None = None
    execution_provider: str = "auto"
    input_width: int = 640
    input_height: int = 640
    class_id: int = 0
    output_format: str = "xyxy_score_class"
    coordinates_normalized: bool = False
    min_area: float = 80.0
    max_area: float = 50000.0
    threshold_mode: str = "adaptive"
    reject_specular_highlights: bool = True
    specular_v_threshold: float = 245.0
    specular_saturation_max: float = 45.0
    ignore_border_px: int = 4
    priority_w_area: float = 0.45
    priority_w_dist: float = 0.25
    priority_w_conf: float = 0.30


@dataclass(frozen=True, slots=True)
class NetworkConfig:
    destination_host: str
    destination_port: int = 5005
    source_id: str = "laptop-ai-01"
    send_no_detection: bool = True
    heartbeat_interval_s: float = 0.2
    max_packet_bytes: int = 4096


@dataclass(frozen=True, slots=True)
class DebugConfig:
    show_window: bool = False
    save_video: bool = False
    log_level: str = "INFO"
    summary_interval_s: float = 5.0


@dataclass(frozen=True, slots=True)
class PerformanceConfig:
    """Laptop inference runtime tuning; zero thread counts keep runtime defaults."""

    opencv_num_threads: int = 0
    opencv_use_opencl: bool = False
    onnx_intra_op_threads: int = 0
    onnx_inter_op_threads: int = 0
    onnx_execution_mode: str = "sequential"
    onnx_graph_optimization: str = "all"
    onnx_enable_cpu_mem_arena: bool = True
    onnx_device_id: int = 0


@dataclass(frozen=True, slots=True)
class AppConfig:
    video: VideoConfig
    detector: DetectorConfig
    network: NetworkConfig
    debug: DebugConfig
    performance: PerformanceConfig


def _mapping(value: Any, section: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{section} must be a YAML mapping")
    return value


def load_config(path: str | Path) -> AppConfig:
    """Load and validate a laptop AI YAML configuration file."""
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError("configuration root must be a YAML mapping")

    video_raw = _mapping(raw.get("video"), "video")
    detector_raw = _mapping(raw.get("detector"), "detector")
    network_raw = _mapping(raw.get("network"), "network")
    debug_raw = _mapping(raw.get("debug"), "debug")
    performance_raw = _mapping(raw.get("performance"), "performance")
    if "source" not in video_raw:
        raise ValueError("video.source is required")
    if "destination_host" not in network_raw:
        raise ValueError("network.destination_host is required")

    video = VideoConfig(**video_raw)
    detector = DetectorConfig(**detector_raw)
    network = NetworkConfig(**network_raw)
    debug = DebugConfig(**debug_raw)
    performance = PerformanceConfig(**performance_raw)
    _validate(video, detector, network, debug, performance)
    return AppConfig(
        video=video,
        detector=detector,
        network=network,
        debug=debug,
        performance=performance,
    )


def _validate(
    video: VideoConfig,
    detector: DetectorConfig,
    network: NetworkConfig,
    debug: DebugConfig,
    performance: PerformanceConfig,
) -> None:
    if isinstance(video.source, bool) or not isinstance(video.source, (str, int)):
        raise ValueError("video.source must be a URL/path string or camera integer")
    if isinstance(video.source, str) and not video.source.strip():
        raise ValueError("video.source cannot be empty")
    if video.backend not in {"opencv", "gstreamer"}:
        raise ValueError("video.backend must be 'opencv' or 'gstreamer'")
    if video.reconnect_interval_s <= 0.0 or video.max_consecutive_failures < 1:
        raise ValueError("video reconnect settings must be positive")
    if min(video.frame_width, video.frame_height, video.process_every_n_frames) < 1:
        raise ValueError("video dimensions and process_every_n_frames must be positive")
    if video.max_frame_age_s <= 0.0:
        raise ValueError("video.max_frame_age_s must be positive")
    if detector.backend not in {"opencv", "onnx"}:
        raise ValueError("detector.backend must be 'opencv' or 'onnx'")
    provider = (
        detector.execution_provider.strip().lower()
        if isinstance(detector.execution_provider, str)
        else ""
    )
    if provider not in {
        "auto",
        "cpu",
        "cuda",
        "directml",
        "dml",
    }:
        raise ValueError(
            "detector.execution_provider must be auto, cpu, cuda, or directml"
        )
    if not 0.0 <= detector.confidence_threshold <= 1.0:
        raise ValueError("detector.confidence_threshold must be within [0, 1]")
    if min(detector.input_width, detector.input_height) < 1:
        raise ValueError("detector input dimensions must be positive")
    if detector.min_area <= 0.0 or detector.max_area < detector.min_area:
        raise ValueError("detector area limits must satisfy 0 < min_area <= max_area")
    if detector.threshold_mode not in {"adaptive", "otsu", "fixed"}:
        raise ValueError("detector.threshold_mode must be adaptive, otsu, or fixed")
    if not isinstance(network.destination_host, str) or not network.destination_host:
        raise ValueError("network.destination_host cannot be empty")
    if not isinstance(network.source_id, str) or not network.source_id:
        raise ValueError("network.source_id cannot be empty")
    if not 1 <= network.destination_port <= 65535:
        raise ValueError("network.destination_port must be within [1, 65535]")
    if network.heartbeat_interval_s <= 0.0 or network.max_packet_bytes < 512:
        raise ValueError("network heartbeat and packet size settings are invalid")
    if debug.summary_interval_s <= 0.0:
        raise ValueError("debug.summary_interval_s must be positive")
    thread_counts = (
        performance.opencv_num_threads,
        performance.onnx_intra_op_threads,
        performance.onnx_inter_op_threads,
    )
    if any(value < 0 for value in thread_counts):
        raise ValueError("performance thread counts cannot be negative")
    if (
        isinstance(performance.onnx_device_id, bool)
        or not isinstance(performance.onnx_device_id, int)
        or performance.onnx_device_id < 0
    ):
        raise ValueError("performance.onnx_device_id must be a non-negative integer")
    if performance.onnx_execution_mode not in {"sequential", "parallel"}:
        raise ValueError(
            "performance.onnx_execution_mode must be sequential or parallel"
        )
    if performance.onnx_graph_optimization not in {
        "disabled",
        "basic",
        "extended",
        "all",
    }:
        raise ValueError(
            "performance.onnx_graph_optimization must be disabled, basic, "
            "extended, or all"
        )
