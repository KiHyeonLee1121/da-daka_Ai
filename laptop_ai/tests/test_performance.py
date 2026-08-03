from laptop_ai.config import PerformanceConfig, load_config
from laptop_ai.performance import create_onnx_session_options


class FakeSessionOptions:
    pass


class FakeExecutionMode:
    ORT_PARALLEL = "parallel"
    ORT_SEQUENTIAL = "sequential"


class FakeGraphOptimizationLevel:
    ORT_DISABLE_ALL = "disabled"
    ORT_ENABLE_BASIC = "basic"
    ORT_ENABLE_EXTENDED = "extended"
    ORT_ENABLE_ALL = "all"


class FakeOrt:
    SessionOptions = FakeSessionOptions
    ExecutionMode = FakeExecutionMode
    GraphOptimizationLevel = FakeGraphOptimizationLevel


def test_onnx_session_options_apply_laptop_tuning() -> None:
    options = create_onnx_session_options(
        FakeOrt,
        PerformanceConfig(
            onnx_intra_op_threads=4,
            onnx_inter_op_threads=2,
            onnx_execution_mode="parallel",
            onnx_graph_optimization="extended",
            onnx_enable_cpu_mem_arena=False,
        ),
    )
    assert options.intra_op_num_threads == 4
    assert options.inter_op_num_threads == 2
    assert options.execution_mode == "parallel"
    assert options.graph_optimization_level == "extended"
    assert not options.enable_cpu_mem_arena


def test_directml_session_options_force_supported_execution_settings() -> None:
    options = create_onnx_session_options(
        FakeOrt,
        PerformanceConfig(onnx_execution_mode="parallel"),
        execution_provider="DmlExecutionProvider",
    )
    assert options.execution_mode == "sequential"
    assert not options.enable_mem_pattern


def test_primary_config_is_headless_and_graph_optimized() -> None:
    config = load_config("config/laptop_ai.yaml")
    assert not config.debug.show_window
    assert config.detector.execution_provider == "auto"
    assert config.performance.onnx_graph_optimization == "all"
    assert config.performance.onnx_device_id == 0
