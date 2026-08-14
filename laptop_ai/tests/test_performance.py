from laptop_ai.config import PerformanceConfig, load_config
from laptop_ai.performance import (
    create_onnx_provider_options,
    create_onnx_session_options,
)


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


def test_gpu_provider_options_enable_linux_nvidia_tuning() -> None:
    options = create_onnx_provider_options(
        PerformanceConfig(
            onnx_device_id=2,
            onnx_cuda_prefer_nhwc=True,
            onnx_cuda_enable_graph=True,
            onnx_cuda_use_tf32=True,
            onnx_cuda_arena_extend_strategy="kNextPowerOfTwo",
            onnx_cuda_cudnn_conv_algo_search="EXHAUSTIVE",
            onnx_tensorrt_cache_path=".runtime/test-cache",
        )
    )
    assert options["CUDAExecutionProvider"] == {
        "device_id": "2",
        "do_copy_in_default_stream": "1",
        "arena_extend_strategy": "kNextPowerOfTwo",
        "cudnn_conv_algo_search": "EXHAUSTIVE",
        "cudnn_conv_use_max_workspace": "1",
        "enable_cuda_graph": "1",
        "use_tf32": "1",
        "prefer_nhwc": "1",
    }
    assert options["TensorrtExecutionProvider"]["trt_fp16_enable"] == "1"
    assert options["TensorrtExecutionProvider"]["trt_engine_cache_enable"] == "1"
    assert options["TensorrtExecutionProvider"]["trt_timing_cache_enable"] == "1"
    assert options["TensorrtExecutionProvider"]["trt_engine_cache_path"].endswith(
        "test-cache"
    )


def test_primary_config_targets_linux_nvidia_gpu() -> None:
    config = load_config("config/laptop_ai.yaml")
    assert not config.debug.show_window
    assert config.video.backend == "gstreamer"
    assert config.detector.backend == "onnx"
    assert config.detector.execution_provider == "cuda"
    assert config.detector.require_gpu
    assert config.performance.onnx_graph_optimization == "all"
    assert config.performance.onnx_device_id == 0
    assert config.performance.opencv_num_threads == 2
    assert config.performance.onnx_intra_op_threads == 1
    assert config.performance.onnx_inter_op_threads == 1
    assert config.performance.onnx_warmup_runs == 20
    assert config.performance.onnx_use_io_binding
    assert config.performance.onnx_cuda_enable_graph
    assert config.performance.cuda_module_loading_lazy
