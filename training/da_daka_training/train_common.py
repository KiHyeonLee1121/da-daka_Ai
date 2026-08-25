"""Shared fail-closed configuration, resume and run metadata helpers."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import random
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import yaml

from da_daka_training.release import (
    DEFAULT_DATASET_FINGERPRINT,
    DEFAULT_DATASET_VERSION,
    verify_dataset_release,
)


def load_config(path):
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("training config must be a YAML object")
    return raw


def add_training_arguments(parser):
    """Add portable path, identity and resume arguments to a trainer parser."""
    parser.add_argument("--config", required=True)
    parser.add_argument("--dataset-root")
    parser.add_argument("--output-dir")
    parser.add_argument("--artifact-dir")
    parser.add_argument("--device")
    parser.add_argument("--resume")
    parser.add_argument("--expected-dataset-version")
    parser.add_argument("--expected-dataset-fingerprint")


def resolve_training_config(args):
    """Resolve CLI -> environment -> YAML without embedding machine paths."""
    config = load_config(args.config)
    dataset_root = (
        args.dataset_root
        or os.environ.get("DA_DAKA_DATASET_ROOT")
        or config.get("dataset_root")
    )
    output_dir = (
        args.output_dir
        or os.environ.get("DA_DAKA_OUTPUT_DIR")
        or config.get("output_dir")
    )
    artifact_dir = (
        args.artifact_dir
        or os.environ.get("DA_DAKA_ARTIFACT_DIR")
        or config.get("artifact_dir")
    )
    if not dataset_root:
        raise ValueError(
            "dataset root is required via --dataset-root, "
            "DA_DAKA_DATASET_ROOT, or config.dataset_root"
        )
    if not output_dir:
        raise ValueError(
            "output directory is required via --output-dir, "
            "DA_DAKA_OUTPUT_DIR, or config.output_dir"
        )
    config["dataset_root"] = str(Path(dataset_root).expanduser().resolve())
    config["output_dir"] = str(Path(output_dir).expanduser().resolve())
    if artifact_dir:
        config["artifact_dir"] = str(Path(artifact_dir).expanduser().resolve())
    if args.device:
        config["device"] = args.device
    release = dict(config.get("dataset_release") or {})
    release["dataset_version"] = (
        args.expected_dataset_version
        or os.environ.get("DA_DAKA_DATASET_VERSION")
        or release.get("dataset_version")
        or DEFAULT_DATASET_VERSION
    )
    release["dataset_fingerprint"] = (
        args.expected_dataset_fingerprint
        or os.environ.get("DA_DAKA_DATASET_FINGERPRINT")
        or release.get("dataset_fingerprint")
        or DEFAULT_DATASET_FINGERPRINT
    )
    release.setdefault("verification_mode", "full")
    config["dataset_release"] = release
    return config


def dataset_manifest(root):
    return json.loads(
        (Path(root) / "dataset_manifest.json").read_text(encoding="utf-8")
    )


def verify_training_dataset(config):
    """Require the configured immutable release before loaders or models run."""
    release = config["dataset_release"]
    return verify_dataset_release(
        config["dataset_root"],
        expected_version=str(release["dataset_version"]),
        expected_fingerprint=str(release["dataset_fingerprint"]),
        mode=str(release.get("verification_mode", "full")),
    )


def git_commit():
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def choose_device(requested):
    import torch

    device = torch.device(requested)
    if device.type == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA training was requested but is unavailable")
        if device.index is not None and device.index >= torch.cuda.device_count():
            raise RuntimeError(
                f"CUDA device index {device.index} is unavailable; "
                f"device_count={torch.cuda.device_count()}"
            )
        # Allocate and synchronize before dataset hashing, output creation, or
        # pretrained-weight downloads so broken CUDA runtimes fail immediately.
        torch.empty((1,), device=device)
        torch.cuda.synchronize(device)
    return device


def seed_training(seed, *, deterministic=True):
    """Seed Python/NumPy/Torch and request deterministic kernels when enabled."""
    import torch

    value = int(seed)
    random.seed(value)
    np.random.seed(value)
    torch.manual_seed(value)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(value)
    if deterministic:
        torch.use_deterministic_algorithms(True)
        if hasattr(torch.backends, "cudnn"):
            torch.backends.cudnn.benchmark = False
            torch.backends.cudnn.deterministic = True
    return value


def prepare_run_directories(config, *, resume_path=None):
    """Create a local run and optional persistent artifact mirror safely."""
    output = Path(config["output_dir"])
    artifact = Path(config["artifact_dir"]) if config.get("artifact_dir") else None
    if output.exists() and resume_path is None:
        raise FileExistsError(f"output directory already exists: {output}")
    output.mkdir(parents=True, exist_ok=resume_path is not None)
    (output / "checkpoints").mkdir(exist_ok=True)
    if artifact is not None and artifact != output:
        if artifact.exists() and resume_path is None:
            raise FileExistsError(f"artifact directory already exists: {artifact}")
        artifact.mkdir(parents=True, exist_ok=resume_path is not None)
        (artifact / "checkpoints").mkdir(exist_ok=True)
    return output, artifact


def create_run_metadata(task, config, release_report, *, resume_path=None, run_id=None):
    """Record enough software/hardware context to reproduce or audit a run."""
    import torch

    try:
        import torchvision

        torchvision_version = torchvision.__version__
    except (ImportError, AttributeError):
        torchvision_version = "unavailable"
    cuda = None
    if torch.cuda.is_available():
        device_index = torch.cuda.current_device()
        properties = torch.cuda.get_device_properties(device_index)
        cuda = {
            "device_index": device_index,
            "device_name": properties.name,
            "compute_capability": list(torch.cuda.get_device_capability(device_index)),
            "total_memory_bytes": int(properties.total_memory),
            "torch_cuda_version": torch.version.cuda,
            "cudnn_version": torch.backends.cudnn.version(),
        }
    return {
        "run_id": run_id or uuid.uuid4().hex,
        "task": task,
        "status": "RUNNING",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "resumed_from": str(Path(resume_path).resolve()) if resume_path else None,
        "git_commit": git_commit(),
        "config_fingerprint": training_config_fingerprint(config),
        "config": config,
        "dataset_verification": release_report,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "torch": torch.__version__,
            "torchvision": torchvision_version,
            "cuda": cuda,
        },
    }


def finish_run_metadata(metadata, *, best_epoch, best_metric):
    value = dict(metadata)
    value.update(
        {
            "status": "COMPLETED",
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "best_epoch": int(best_epoch),
            "best_metric": float(best_metric),
        }
    )
    return value


def training_config_fingerprint(config):
    """Hash resume-sensitive settings while allowing path/device relocation."""
    excluded = {
        "dataset_root",
        "output_dir",
        "artifact_dir",
        "device",
        "epochs",
        "workers",
    }
    canonical = {key: value for key, value in config.items() if key not in excluded}
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def capture_rng_state():
    import torch

    return {
        "python": random.getstate(),
        "numpy": np.random.get_state(),
        "torch_cpu": torch.get_rng_state(),
        "torch_cuda": torch.cuda.get_rng_state_all()
        if torch.cuda.is_available()
        else None,
    }


def restore_rng_state(state):
    import torch

    if not state:
        return
    random.setstate(state["python"])
    np.random.set_state(state["numpy"])
    torch.set_rng_state(state["torch_cpu"])
    if state.get("torch_cuda") is not None and torch.cuda.is_available():
        torch.cuda.set_rng_state_all(state["torch_cuda"])


def resume_training(checkpoint_path, *, task, config, model, optimizer):
    """Load an identity/config-locked checkpoint and restore optimizer/RNG."""
    import torch

    if not checkpoint_path:
        return 1, [], float("-inf"), 0, None
    path = Path(checkpoint_path).expanduser().resolve()
    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    if checkpoint.get("task") != task:
        raise ValueError(
            f"resume checkpoint task mismatch: {checkpoint.get('task')!r} != {task!r}"
        )
    release = config["dataset_release"]
    if checkpoint.get("dataset_version") != release["dataset_version"]:
        raise ValueError("resume checkpoint dataset_version mismatch")
    if checkpoint.get("dataset_fingerprint") != release["dataset_fingerprint"]:
        raise ValueError("resume checkpoint dataset_fingerprint mismatch")
    expected_config = training_config_fingerprint(config)
    if checkpoint.get("training_config_fingerprint") != expected_config:
        raise ValueError("resume checkpoint training configuration mismatch")
    model.load_state_dict(checkpoint["model_state"])
    optimizer.load_state_dict(checkpoint["optimizer_state"])
    restore_rng_state(checkpoint.get("rng_state"))
    epoch = int(checkpoint["epoch"])
    history = list(checkpoint.get("history", []))
    best_metric = float(checkpoint.get("best_metric", float("-inf")))
    best_epoch = int(checkpoint.get("best_epoch", 0))
    return epoch + 1, history, best_metric, best_epoch, checkpoint.get("run_id")


def copy_resume_best_checkpoint(checkpoint_path, output, *, task, config):
    """Carry the persistent best checkpoint into a resumed local run."""
    if not checkpoint_path:
        return
    import torch

    resume_path = Path(checkpoint_path).expanduser().resolve()
    candidate = (
        resume_path if resume_path.name == "best.pt" else resume_path.parent / "best.pt"
    )
    if not candidate.is_file():
        raise FileNotFoundError(
            f"resume requires the sibling best.pt checkpoint: {candidate}"
        )
    checkpoint = torch.load(candidate, map_location="cpu", weights_only=False)
    release = config["dataset_release"]
    if checkpoint.get("task") != task:
        raise ValueError("best resume checkpoint task mismatch")
    if checkpoint.get("dataset_version") != release["dataset_version"]:
        raise ValueError("best resume checkpoint dataset_version mismatch")
    if checkpoint.get("dataset_fingerprint") != release["dataset_fingerprint"]:
        raise ValueError("best resume checkpoint dataset_fingerprint mismatch")
    if checkpoint.get("training_config_fingerprint") != training_config_fingerprint(
        config
    ):
        raise ValueError("best resume checkpoint training configuration mismatch")
    target = Path(output) / "checkpoints/best.pt"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    shutil.copy2(candidate, temporary)
    os.replace(temporary, target)


def checkpoint_payload(
    *,
    task,
    model,
    optimizer,
    config,
    manifest,
    epoch,
    history,
    best_metric,
    best_epoch,
    run_id,
    validation_metrics,
):
    return {
        "checkpoint_version": 2,
        "task": task,
        "epoch": int(epoch),
        "model_state": model.state_dict(),
        "optimizer_state": optimizer.state_dict(),
        "rng_state": capture_rng_state(),
        "history": history,
        "best_metric": float(best_metric),
        "best_epoch": int(best_epoch),
        "run_id": run_id,
        "config": config,
        "training_config_fingerprint": training_config_fingerprint(config),
        "dataset_version": manifest["dataset_version"],
        "dataset_fingerprint": manifest["dataset_fingerprint"],
        "git_commit": git_commit(),
        "validation_metrics": validation_metrics,
    }


def save_checkpoint(path, payload):
    """Write a checkpoint atomically so interrupted Drive syncs are rejected."""
    import torch

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    torch.save(payload, temporary)
    os.replace(temporary, path)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def mirror_artifacts(output, artifact, relative_paths):
    """Atomically mirror selected small/checkpoint artifacts to persistent Drive."""
    if artifact is None or Path(artifact) == Path(output):
        return
    output = Path(output)
    artifact = Path(artifact)
    for relative in relative_paths:
        source = output / relative
        if not source.is_file():
            continue
        target = artifact / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp")
        shutil.copy2(source, temporary)
        os.replace(temporary, target)


def archive_directory(directory, archive_path):
    """Pack many small evaluation files before writing them to Drive."""
    directory = Path(directory)
    archive_path = Path(archive_path)
    if not directory.is_dir():
        raise FileNotFoundError(f"cannot archive missing directory: {directory}")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_base = archive_path.parent / f".{archive_path.stem}.tmp"
    generated = Path(
        shutil.make_archive(
            str(temporary_base),
            "zip",
            root_dir=directory,
        )
    )
    os.replace(generated, archive_path)
