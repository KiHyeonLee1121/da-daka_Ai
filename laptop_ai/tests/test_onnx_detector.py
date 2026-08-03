from pathlib import Path

import pytest
import numpy as np

from laptop_ai.config import DetectorConfig
from laptop_ai.onnx_detector import (
    OnnxDetector,
    preprocess_onnx_frame,
    select_onnx_providers,
)
from laptop_ai.onnx_postprocess import postprocess_xyxy_score_class


def test_missing_onnx_model_path_has_clear_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing.onnx"
    with pytest.raises(FileNotFoundError, match="does not exist"):
        OnnxDetector(DetectorConfig(backend="onnx", model_path=str(missing)))


def test_model_specific_postprocess_isolated_from_runtime() -> None:
    output = np.array([[64, 64, 320, 320, 0.9, 0]], dtype=np.float32)
    candidate = postprocess_xyxy_score_class(
        output,
        image_width=640,
        image_height=480,
        input_width=640,
        input_height=640,
        confidence_threshold=0.5,
        class_id=0,
        coordinates_normalized=False,
    )
    assert candidate is not None
    assert candidate.bbox == pytest.approx((64, 48, 256, 192))


def test_auto_provider_prefers_cuda_then_keeps_cpu_fallback() -> None:
    providers, selected, fallback = select_onnx_providers(
        "auto",
        ["CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider"],
        device_id=2,
    )
    assert selected == "CUDAExecutionProvider"
    assert providers == [
        ("CUDAExecutionProvider", {"device_id": "2"}),
        "CPUExecutionProvider",
    ]
    assert not fallback


def test_auto_provider_prefers_tensorrt_with_cuda_subgraph_fallback() -> None:
    options = {
        "TensorrtExecutionProvider": {"trt_fp16_enable": "1"},
        "CUDAExecutionProvider": {"prefer_nhwc": "1"},
    }
    providers, selected, fallback = select_onnx_providers(
        "auto",
        [
            "TensorrtExecutionProvider",
            "CUDAExecutionProvider",
            "CPUExecutionProvider",
        ],
        provider_options=options,
    )
    assert selected == "TensorrtExecutionProvider"
    assert providers == [
        (
            "TensorrtExecutionProvider",
            {"trt_fp16_enable": "1", "device_id": "0"},
        ),
        ("CUDAExecutionProvider", {"prefer_nhwc": "1", "device_id": "0"}),
        "CPUExecutionProvider",
    ]
    assert not fallback


def test_requested_tensorrt_falls_back_to_cuda() -> None:
    providers, selected, fallback = select_onnx_providers(
        "tensorrt",
        ["CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    assert selected == "CUDAExecutionProvider"
    assert providers == [
        ("CUDAExecutionProvider", {"device_id": "0"}),
        "CPUExecutionProvider",
    ]
    assert fallback


def test_auto_provider_uses_directml_for_amd_windows_gpu() -> None:
    providers, selected, fallback = select_onnx_providers(
        "auto",
        ["DmlExecutionProvider", "CPUExecutionProvider"],
    )
    assert selected == "DmlExecutionProvider"
    assert providers == [
        ("DmlExecutionProvider", {"device_id": "0"}),
        "CPUExecutionProvider",
    ]
    assert not fallback


def test_missing_requested_gpu_provider_falls_back_to_cpu() -> None:
    providers, selected, fallback = select_onnx_providers(
        "directml",
        ["CPUExecutionProvider"],
    )
    assert providers == ["CPUExecutionProvider"]
    assert selected == "CPUExecutionProvider"
    assert fallback


def test_provider_selection_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="auto, cpu, cuda, tensorrt, or directml"):
        select_onnx_providers("rocm", ["CPUExecutionProvider"])


def test_provider_selection_rejects_invalid_device_id() -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        select_onnx_providers("auto", ["CPUExecutionProvider"], device_id=-1)


def test_preprocess_is_contiguous_nchw_rgb_float() -> None:
    frame = np.array(
        [
            [[0, 64, 255], [255, 128, 0]],
            [[30, 20, 10], [60, 50, 40]],
        ],
        dtype=np.uint8,
    )
    tensor = preprocess_onnx_frame(
        frame,
        input_width=2,
        input_height=2,
    )
    assert tensor.shape == (1, 3, 2, 2)
    assert tensor.dtype == np.float32
    assert tensor.flags.c_contiguous
    assert tensor[0, :, 0, 0] == pytest.approx([1.0, 64 / 255, 0.0])
