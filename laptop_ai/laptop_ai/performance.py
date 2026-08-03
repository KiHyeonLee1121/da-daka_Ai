"""Laptop CPU/GPU runtime tuning kept separate from detection logic."""

from __future__ import annotations

import logging
from typing import Any

from laptop_ai.config import PerformanceConfig


logger = logging.getLogger(__name__)


def configure_opencv(config: PerformanceConfig) -> None:
    """Apply optional OpenCV thread and OpenCL settings once at startup."""
    import cv2

    if config.opencv_num_threads > 0:
        cv2.setNumThreads(config.opencv_num_threads)
    cv2.ocl.setUseOpenCL(config.opencv_use_opencl)
    logger.info(
        "OpenCV runtime threads=%s opencl=%s",
        config.opencv_num_threads or "auto",
        cv2.ocl.useOpenCL(),
    )


def create_onnx_session_options(
    ort: Any,
    config: PerformanceConfig,
    *,
    execution_provider: str = "CPUExecutionProvider",
) -> Any:
    """Create safe ONNX Runtime options for the selected execution provider."""
    options = ort.SessionOptions()
    if config.onnx_intra_op_threads > 0:
        options.intra_op_num_threads = config.onnx_intra_op_threads
    if config.onnx_inter_op_threads > 0:
        options.inter_op_num_threads = config.onnx_inter_op_threads
    directml = execution_provider == "DmlExecutionProvider"
    if directml:
        # DirectML rejects parallel execution and memory-pattern optimization.
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.enable_mem_pattern = False
    else:
        options.execution_mode = (
            ort.ExecutionMode.ORT_PARALLEL
            if config.onnx_execution_mode == "parallel"
            else ort.ExecutionMode.ORT_SEQUENTIAL
        )
    optimization_levels = {
        "disabled": ort.GraphOptimizationLevel.ORT_DISABLE_ALL,
        "basic": ort.GraphOptimizationLevel.ORT_ENABLE_BASIC,
        "extended": ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED,
        "all": ort.GraphOptimizationLevel.ORT_ENABLE_ALL,
    }
    options.graph_optimization_level = optimization_levels[
        config.onnx_graph_optimization
    ]
    options.enable_cpu_mem_arena = config.onnx_enable_cpu_mem_arena
    return options
