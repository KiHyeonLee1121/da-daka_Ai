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
from laptop_ai.onnx_detector import select_onnx_providers
from laptop_ai.performance import create_onnx_session_options


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark ONNX Runtime inference without camera/network overhead"
    )
    parser.add_argument("--model", required=True, help="Path to a fixed-shape ONNX model")
    parser.add_argument(
        "--provider",
        choices=("auto", "cpu", "cuda", "directml"),
        default="auto",
    )
    parser.add_argument("--device-id", type=int, default=0)
    parser.add_argument("--intra-op-threads", type=int, default=0)
    parser.add_argument("--warmup", type=int, default=15)
    parser.add_argument("--iterations", type=int, default=80)
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
    dtypes = {
        "tensor(float)": np.float32,
        "tensor(float16)": np.float16,
    }
    try:
        return dtypes[input_meta.type]
    except KeyError as exc:
        raise ValueError(
            f"benchmark supports float/float16 inputs, got {input_meta.type}"
        ) from exc


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def main() -> int:
    args = _parse_args()
    if args.warmup < 0 or args.iterations < 1:
        raise ValueError("warmup must be non-negative and iterations must be positive")
    model_path = Path(args.model).expanduser()
    if not model_path.is_file():
        raise FileNotFoundError(f"ONNX model file does not exist: {model_path}")

    import onnxruntime as ort

    performance = PerformanceConfig(
        onnx_intra_op_threads=args.intra_op_threads,
        onnx_device_id=args.device_id,
    )
    providers, selected, fallback = select_onnx_providers(
        args.provider,
        ort.get_available_providers(),
        device_id=args.device_id,
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
    tensor = np.random.default_rng(1121).random(
        _fixed_shape(input_meta),
        dtype=np.float32,
    ).astype(_input_dtype(input_meta), copy=False)

    for _ in range(args.warmup):
        session.run(None, {input_meta.name: tensor})
    latencies_ms: list[float] = []
    for _ in range(args.iterations):
        started = time.perf_counter_ns()
        session.run(None, {input_meta.name: tensor})
        latencies_ms.append((time.perf_counter_ns() - started) / 1e6)

    median_ms = statistics.median(latencies_ms)
    report = {
        "model": str(model_path.resolve()),
        "onnxruntime_version": ort.__version__,
        "requested_provider": args.provider,
        "selected_provider": selected,
        "active_providers": session.get_providers(),
        "cpu_fallback": fallback,
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
