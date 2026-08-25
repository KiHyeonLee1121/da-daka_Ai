"""Colab/Linux GPU preflight with an intentionally fail-fast CUDA policy."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys


def gpu_environment_report(*, require_cuda: bool = True) -> dict:
    if sys.version_info < (3, 10):
        raise RuntimeError(
            f"Python >= 3.10 is required, found {platform.python_version()}"
        )
    try:
        import torch
        import torchvision
    except ImportError as exc:
        raise RuntimeError(
            "PyTorch and torchvision must be installed before the GPU preflight"
        ) from exc
    cuda_available = bool(torch.cuda.is_available())
    if require_cuda and not cuda_available:
        raise RuntimeError(
            "COLAB GPU REQUIRED: torch.cuda.is_available() is false. "
            "Select a GPU runtime before mounting Drive, staging data, or training."
        )
    cuda = None
    if cuda_available:
        index = torch.cuda.current_device()
        properties = torch.cuda.get_device_properties(index)
        cuda = {
            "device_index": index,
            "device_name": properties.name,
            "compute_capability": list(torch.cuda.get_device_capability(index)),
            "total_memory_bytes": int(properties.total_memory),
            "torch_cuda_version": torch.version.cuda,
            "cudnn_version": torch.backends.cudnn.version(),
        }
        torch.empty((1,), device="cuda")
        torch.cuda.synchronize()
    nvidia_smi = None
    executable = shutil.which("nvidia-smi")
    if executable:
        completed = subprocess.run(
            [
                executable,
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if completed.returncode == 0:
            nvidia_smi = completed.stdout.strip()
    return {
        "status": "GPU_READY" if cuda_available else "CPU_ONLY",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "torch": torch.__version__,
        "torchvision": torchvision.__version__,
        "cuda": cuda,
        "nvidia_smi": nvidia_smi,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--allow-cpu",
        action="store_true",
        help="diagnostic only; production Colab training should not use this",
    )
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                gpu_environment_report(require_cuda=not args.allow_cpu),
                indent=2,
                sort_keys=True,
            )
        )
    except RuntimeError as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    main()
