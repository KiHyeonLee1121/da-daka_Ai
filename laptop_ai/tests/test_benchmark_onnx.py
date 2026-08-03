from types import SimpleNamespace

import numpy as np
import pytest

from laptop_ai.benchmark_onnx import _fixed_shape, _input_dtype, _percentile


def test_benchmark_accepts_fixed_float_input() -> None:
    input_meta = SimpleNamespace(shape=[1, 3, 640, 640], type="tensor(float)")
    assert _fixed_shape(input_meta) == (1, 3, 640, 640)
    assert _input_dtype(input_meta) is np.float32


def test_benchmark_rejects_dynamic_input_shape() -> None:
    input_meta = SimpleNamespace(shape=["batch", 3, 640, 640])
    with pytest.raises(ValueError, match="fixed input shape"):
        _fixed_shape(input_meta)


def test_benchmark_percentile_uses_nearest_observation() -> None:
    assert _percentile([5.0, 1.0, 3.0, 2.0, 4.0], 0.95) == 5.0
