"""Reusable ONNX Runtime execution with optional device I/O binding."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np


logger = logging.getLogger(__name__)


def onnx_tensor_dtype(type_name: str) -> Any:
    """Map common ONNX Runtime tensor type strings to NumPy dtypes."""
    dtypes = {
        "tensor(float)": np.float32,
        "tensor(float16)": np.float16,
        "tensor(double)": np.float64,
        "tensor(int64)": np.int64,
        "tensor(int32)": np.int32,
        "tensor(uint8)": np.uint8,
        "tensor(int8)": np.int8,
        "tensor(bool)": np.bool_,
    }
    try:
        return dtypes[type_name]
    except KeyError as exc:
        raise ValueError(f"unsupported ONNX tensor type: {type_name}") from exc


def fixed_tensor_shape(shape: Any) -> tuple[int, ...] | None:
    """Return a positive fixed shape, or None for a dynamic tensor."""
    if not shape or any(isinstance(value, str) or value is None for value in shape):
        return None
    resolved = tuple(int(value) for value in shape)
    if any(value < 1 for value in resolved):
        return None
    return resolved


class OnnxInferenceRunner:
    """Run a session and reuse fixed device output buffers when possible."""

    _DEVICE_NAMES = {
        "DmlExecutionProvider": "dml",
        "CUDAExecutionProvider": "cuda",
        "TensorrtExecutionProvider": "cuda",
    }

    def __init__(
        self,
        ort: Any,
        session: Any,
        *,
        selected_provider: str,
        device_id: int,
        use_io_binding: bool,
    ) -> None:
        self._ort = ort
        self._session = session
        self._input = session.get_inputs()[0]
        self._outputs = tuple(session.get_outputs())
        self._device_id = device_id
        self._device_name = (
            self._DEVICE_NAMES.get(selected_provider) if use_io_binding else None
        )
        self._binding = None
        self._output_values: tuple[Any, ...] = ()
        self._mode = "disabled"
        if self._device_name is not None:
            self._configure_binding()

    @property
    def input_name(self) -> str:
        return self._input.name

    @property
    def input_dtype(self) -> Any:
        return onnx_tensor_dtype(self._input.type)

    @property
    def io_binding_mode(self) -> str:
        return self._mode

    def _configure_binding(self) -> None:
        try:
            shapes = [fixed_tensor_shape(output.shape) for output in self._outputs]
            if all(shape is not None for shape in shapes):
                binding = self._session.io_binding()
                output_values = []
                for output, shape in zip(self._outputs, shapes):
                    value = self._ort.OrtValue.ortvalue_from_shape_and_type(
                        shape,
                        onnx_tensor_dtype(output.type),
                        self._device_name,
                        self._device_id,
                    )
                    binding.bind_ortvalue_output(output.name, value)
                    output_values.append(value)
                self._binding = binding
                self._output_values = tuple(output_values)
                self._mode = "fixed-output"
            else:
                self._mode = "dynamic-output"
        except (AttributeError, RuntimeError, ValueError) as exc:
            self._device_name = None
            self._binding = None
            self._output_values = ()
            self._mode = "disabled"
            logger.warning("ONNX I/O binding unavailable; using session.run: %s", exc)

    def run(self, tensor: np.ndarray) -> list[np.ndarray]:
        """Run inference and return CPU NumPy outputs for post-processing."""
        if self._device_name is None:
            return self._session.run(None, {self._input.name: tensor})

        if self._binding is not None:
            self._binding.clear_binding_inputs()
            self._binding.bind_cpu_input(self._input.name, tensor)
            self._session.run_with_iobinding(self._binding)
            return [value.numpy() for value in self._output_values]

        binding = self._session.io_binding()
        binding.bind_cpu_input(self._input.name, tensor)
        for output in self._outputs:
            binding.bind_output(output.name, self._device_name, self._device_id)
        self._session.run_with_iobinding(binding)
        return binding.copy_outputs_to_cpu()
