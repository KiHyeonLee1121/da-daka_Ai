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
    """Run a session while reusing GPU input/output buffers when shapes permit."""

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
        enable_cuda_graph: bool = False,
    ) -> None:
        self._ort = ort
        self._session = session
        self._input = session.get_inputs()[0]
        self._outputs = tuple(session.get_outputs())
        self._device_id = device_id
        self._selected_provider = selected_provider
        self._device_name = (
            self._DEVICE_NAMES.get(selected_provider) if use_io_binding else None
        )
        self._binding = None
        self._input_value = None
        self._output_values: tuple[Any, ...] = ()
        self._run_options = None
        self._mode = "disabled"
        self._cuda_graph_enabled = False
        self._cuda_graph_requested = bool(enable_cuda_graph)
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

    @property
    def cuda_graph_enabled(self) -> bool:
        return self._cuda_graph_enabled

    def _configure_binding(self) -> None:
        try:
            output_shapes = [fixed_tensor_shape(output.shape) for output in self._outputs]
            fixed_outputs = all(shape is not None for shape in output_shapes)
            fixed_input = fixed_tensor_shape(self._input.shape)
            binding = self._session.io_binding()
            output_values = []

            # CUDA/TensorRT fixed-shape inference benefits from keeping the same
            # device addresses across frames. It also satisfies CUDA Graph's
            # fixed-address requirement when the CUDA EP is selected.
            if (
                fixed_input is not None
                and fixed_outputs
                and self._selected_provider
                in {"CUDAExecutionProvider", "TensorrtExecutionProvider"}
            ):
                self._input_value = self._ort.OrtValue.ortvalue_from_shape_and_type(
                    fixed_input,
                    self.input_dtype,
                    self._device_name,
                    self._device_id,
                )
                binding.bind_ortvalue_input(self._input.name, self._input_value)

            if fixed_outputs:
                for output, shape in zip(self._outputs, output_shapes):
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
                self._mode = (
                    "fixed-input-output"
                    if self._input_value is not None
                    else "fixed-output"
                )
            else:
                self._mode = "dynamic-output"

            if self._cuda_graph_requested:
                if (
                    self._selected_provider == "CUDAExecutionProvider"
                    and self._mode == "fixed-input-output"
                ):
                    self._run_options = self._ort.RunOptions()
                    self._run_options.add_run_config_entry("gpu_graph_id", "0")
                    self._cuda_graph_enabled = True
                else:
                    logger.warning(
                        "CUDA Graph requested but disabled: provider=%s io_binding_mode=%s",
                        self._selected_provider,
                        self._mode,
                    )
        except (AttributeError, RuntimeError, ValueError) as exc:
            self._device_name = None
            self._binding = None
            self._input_value = None
            self._output_values = ()
            self._run_options = None
            self._mode = "disabled"
            self._cuda_graph_enabled = False
            logger.warning("ONNX I/O binding unavailable; using session.run: %s", exc)

    def _validate_tensor(self, tensor: np.ndarray) -> None:
        expected_shape = fixed_tensor_shape(self._input.shape)
        if expected_shape is not None and tuple(tensor.shape) != expected_shape:
            raise ValueError(
                f"ONNX input shape mismatch: expected {expected_shape}, got {tuple(tensor.shape)}"
            )
        expected_dtype = np.dtype(self.input_dtype)
        if tensor.dtype != expected_dtype:
            raise ValueError(
                f"ONNX input dtype mismatch: expected {expected_dtype}, got {tensor.dtype}"
            )

    def run(self, tensor: np.ndarray) -> list[np.ndarray]:
        """Run inference and return CPU NumPy outputs for post-processing."""
        self._validate_tensor(tensor)
        if self._device_name is None:
            return self._session.run(None, {self._input.name: tensor})

        if self._binding is not None:
            if self._input_value is not None:
                # Copy into a stable GPU allocation instead of allocating/binding
                # a new device input every frame.
                self._input_value.update_inplace(tensor)
            else:
                self._binding.clear_binding_inputs()
                self._binding.bind_cpu_input(self._input.name, tensor)

            if self._run_options is None:
                self._session.run_with_iobinding(self._binding)
            else:
                self._session.run_with_iobinding(self._binding, self._run_options)
            return [value.numpy() for value in self._output_values]

        binding = self._session.io_binding()
        binding.bind_cpu_input(self._input.name, tensor)
        for output in self._outputs:
            binding.bind_output(output.name, self._device_name, self._device_id)
        self._session.run_with_iobinding(binding)
        return binding.copy_outputs_to_cpu()
