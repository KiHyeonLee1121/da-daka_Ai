from types import SimpleNamespace

import numpy as np
import pytest

from laptop_ai.onnx_runner import (
    OnnxInferenceRunner,
    fixed_tensor_shape,
    onnx_tensor_dtype,
)


class FakeValue:
    def __init__(self, array) -> None:
        self.array = np.asarray(array)

    def numpy(self):
        return self.array.copy()


class FakeOrtValue:
    @staticmethod
    def ortvalue_from_numpy(array, _device, _device_id):
        return FakeValue(array)

    @staticmethod
    def ortvalue_from_shape_and_type(shape, dtype, _device, _device_id):
        return FakeValue(np.zeros(shape, dtype=dtype))


class FakeOrt:
    OrtValue = FakeOrtValue


class FakeBinding:
    def __init__(self) -> None:
        self.input = None
        self.outputs = []

    def clear_binding_inputs(self) -> None:
        self.input = None

    def bind_ortvalue_input(self, _name, value) -> None:
        self.input = value

    def bind_cpu_input(self, _name, value) -> None:
        self.input = value

    def bind_ortvalue_output(self, _name, value) -> None:
        self.outputs.append(value)

    def bind_output(self, _name, _device, _device_id) -> None:
        pass

    def copy_outputs_to_cpu(self):
        return [np.ones((1, 6), dtype=np.float32)]


class FakeSession:
    def __init__(self, output_shape) -> None:
        self.input = SimpleNamespace(
            name="images",
            shape=[1, 3, 2, 2],
            type="tensor(float)",
        )
        self.output = SimpleNamespace(
            name="detections",
            shape=output_shape,
            type="tensor(float)",
        )
        self.standard_runs = 0
        self.binding_runs = 0

    def get_inputs(self):
        return [self.input]

    def get_outputs(self):
        return [self.output]

    def io_binding(self):
        return FakeBinding()

    def run(self, _outputs, _inputs):
        self.standard_runs += 1
        return [np.zeros((1, 6), dtype=np.float32)]

    def run_with_iobinding(self, _binding):
        self.binding_runs += 1


def test_tensor_helpers_validate_type_and_shape() -> None:
    assert onnx_tensor_dtype("tensor(float)") is np.float32
    assert fixed_tensor_shape([1, 3, 640, 640]) == (1, 3, 640, 640)
    assert fixed_tensor_shape(["batch", 3, 640, 640]) is None
    with pytest.raises(ValueError, match="unsupported ONNX tensor type"):
        onnx_tensor_dtype("tensor(string)")


def test_fixed_output_binding_reuses_device_output() -> None:
    session = FakeSession([1, 6])
    runner = OnnxInferenceRunner(
        FakeOrt,
        session,
        selected_provider="DmlExecutionProvider",
        device_id=0,
        use_io_binding=True,
    )
    outputs = runner.run(np.zeros((1, 3, 2, 2), dtype=np.float32))
    assert runner.io_binding_mode == "fixed-output"
    assert outputs[0].shape == (1, 6)
    assert session.binding_runs == 1
    assert session.standard_runs == 0


def test_dynamic_output_binding_uses_runtime_allocated_output() -> None:
    session = FakeSession(["detections", 6])
    runner = OnnxInferenceRunner(
        FakeOrt,
        session,
        selected_provider="CUDAExecutionProvider",
        device_id=0,
        use_io_binding=True,
    )
    outputs = runner.run(np.zeros((1, 3, 2, 2), dtype=np.float32))
    assert runner.io_binding_mode == "dynamic-output"
    assert outputs[0].shape == (1, 6)
    assert session.binding_runs == 1


def test_cpu_runner_uses_standard_session_run() -> None:
    session = FakeSession([1, 6])
    runner = OnnxInferenceRunner(
        FakeOrt,
        session,
        selected_provider="CPUExecutionProvider",
        device_id=0,
        use_io_binding=True,
    )
    runner.run(np.zeros((1, 3, 2, 2), dtype=np.float32))
    assert runner.io_binding_mode == "disabled"
    assert session.standard_runs == 1
