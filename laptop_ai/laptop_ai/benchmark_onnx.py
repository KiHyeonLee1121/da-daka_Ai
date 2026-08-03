"""Benchmark one fixed-shape ONNX model on an available laptop provider."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import time
from typing import Any

import numpy as np

from laptop_ai.config import PerformanceConfig
from laptop_ai.onnx_detector import preprocess_onnx_frame, select_onnx_providers
from laptop_ai.onnx_runner import OnnxInferenceRunner, onnx_tensor_dtype
from laptop_ai.performance import (
    configure_opencv,
    create_onnx_provider_options,
    create_onnx_session_options,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark ONNX Runtime inference without camera/network overhead"
    )
    parser.add_argument("--model", required=True, help="Path to a fixed-shape ONNX model")
    parser.add_argument(
        "--provider",
        choices=("auto", "cpu", "cuda", "tensorrt", "directml"),
        default="auto",
    )
    parser.add_argument("--device-id", type=int, default=0)
    parser.add_argument("--intra-op-threads", type=int, default=0)
    parser.add_argument("--opencv-threads", type=int, default=0)
    parser.add_argument("--warmup", type=int, default=15)
    parser.add_argument("--iterations", type=int, default=80)
    parser.add_argument(
        "--io-binding",
        action="store_true",
        help="Use device I/O binding and fixed output buffers when supported",
    )
    parser.add_argument(
        "--include-preprocess",
        action="store_true",
        help="Include 640x480 BGR frame preprocessing in each measured iteration",
    )
    parser.add_argument(
        "--input-image",
        help="Use an image and include its preprocessing in measured latency",
    )
    return parser.parse_args()


def _fixed_shape(input_meta: Any) -> tuple[int, ...]:
    shape = input_meta.shape
    if not shape or any(isinstance(value, str) or value is None for value in shape):
        raise ValueError("benchmark requires a model with a fixed input shape")
    resolved = tuple(int(value) for value in shape)
    if any(value < 1 for value in resolved):
        raise ValueError("benchmark input dimensions must be positive")
    return resolved


def _input_dtype(input_meta: Any) -> Any:
    if input_meta.type not in {"tensor(float)", "tensor(float16)"}:
        raise ValueError(
            f"benchmark supports float/float16 inputs, got {input_meta.type}"
        )
    try:
        return onnx_tensor_dtype(input_meta.type)
    except ValueError as exc:
        raise ValueError(
            f"benchmark supports float/float16 inputs, got {input_meta.type}"
        ) from exc


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def main() -> int:
    args = _parse_args()
    if args.warmup < 0 or args.iterations < 1 or args.opencv_threads < 0:
        raise ValueError(
            "warmup/OpenCV threads must be non-negative and iterations positive"
        )
    model_path = Path(args.model).expanduser()
    if not model_path.is_file():
        raise FileNotFoundError(f"ONNX model file does not exist: {model_path}")

    import onnxruntime as ort

    performance = PerformanceConfig(
        opencv_num_threads=args.opencv_threads,
        onnx_intra_op_threads=args.intra_op_threads,
        onnx_device_id=args.device_id,
        onnx_use_io_binding=args.io_binding,
    )
    configure_opencv(performance)
    provider_options = create_onnx_provider_options(performance)
    providers, selected, fallback = select_onnx_providers(
        args.provider,
        ort.get_available_providers(),
        device_id=args.device_id,
        provider_options=provider_options,
    )
    if selected == "TensorrtExecutionProvider":
        Path(performance.onnx_tensorrt_cache_path).expanduser().mkdir(
            parents=True,
            exist_ok=True,
        )
    options = create_onnx_session_options(
        ort,
        performance,
        execution_provider=selected,
    )
    session = ort.InferenceSession(
        str(model_path),
        sess_options=options,
        providers=providers,
    )
    inputs = session.get_inputs()
    if len(inputs) != 1:
        raise ValueError(f"benchmark expects one model input, got {len(inputs)}")
    input_meta = inputs[0]
    input_shape = _fixed_shape(input_meta)
    dtype = _input_dtype(input_meta)
    tensor = np.random.default_rng(1121).random(
        input_shape,
        dtype=np.float32,
    ).astype(dtype, copy=False)
    runner = OnnxInferenceRunner(
        ort,
        session,
        selected_provider=selected,
        device_id=args.device_id,
        use_io_binding=args.io_binding,
    )

    frame = None
    if args.input_image:
        import cv2

        frame = cv2.imread(args.input_image)
        if frame is None:
            raise ValueError(f"cannot read benchmark input image: {args.input_image}")
    elif args.include_preprocess:
        frame = np.random.default_rng(1121).integers(
            0,
            256,
            size=(480, 640, 3),
            dtype=np.uint8,
        )
    includes_preprocess = frame is not None
    if includes_preprocess and (len(input_shape) != 4 or input_shape[1] != 3):
        raise ValueError("preprocessing benchmark requires NCHW input with 3 channels")

    def get_tensor() -> np.ndarray:
        if frame is None:
            return tensor
        return preprocess_onnx_frame(
            frame,
            input_width=input_shape[3],
            input_height=input_shape[2],
            dtype=dtype,
        )

    for _ in range(args.warmup):
        runner.run(get_tensor())
    latencies_ms: list[float] = []
    for _ in range(args.iterations):
        started = time.perf_counter_ns()
        runner.run(get_tensor())
        latencies_ms.append((time.perf_counter_ns() - started) / 1e6)

    median_ms = statistics.median(latencies_ms)
    report = {
        "model": str(model_path.resolve()),
        "onnxruntime_version": ort.__version__,
        "requested_provider": args.provider,
        "selected_provider": selected,
        "active_providers": session.get_providers(),
        "cpu_fallback": fallback,
        "io_binding_mode": runner.io_binding_mode,
        "includes_preprocess": includes_preprocess,
        "device_id": args.device_id,
        "input_shape": list(tensor.shape),
        "iterations": args.iterations,
        "latency_ms_median": median_ms,
        "latency_ms_p95": _percentile(latencies_ms, 0.95),
        "latency_ms_max": max(latencies_ms),
        "fps_from_median": 1000.0 / median_ms,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
