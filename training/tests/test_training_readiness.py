from argparse import Namespace
from pathlib import Path

import yaml
from da_daka_training.release import (
    DEFAULT_DATASET_FINGERPRINT,
    DEFAULT_DATASET_VERSION,
)
from da_daka_training.train_common import (
    prepare_run_directories,
    resolve_training_config,
    training_config_fingerprint,
)


def _args(config, **overrides):
    values = {
        "config": str(config),
        "dataset_root": None,
        "output_dir": None,
        "artifact_dir": None,
        "device": None,
        "resume": None,
        "expected_dataset_version": None,
        "expected_dataset_fingerprint": None,
    }
    values.update(overrides)
    return Namespace(**values)


def test_training_paths_are_injected_by_cli_not_placeholder_config(tmp_path):
    config_path = tmp_path / "training.yaml"
    config_path.write_text(
        yaml.safe_dump({"dataset_root": None, "output_dir": None, "device": "cuda"}),
        encoding="utf-8",
    )
    resolved = resolve_training_config(
        _args(
            config_path,
            dataset_root=str(tmp_path / "dataset"),
            output_dir=str(tmp_path / "run"),
            artifact_dir=str(tmp_path / "drive-run"),
        )
    )
    assert Path(resolved["dataset_root"]) == (tmp_path / "dataset").resolve()
    assert Path(resolved["output_dir"]) == (tmp_path / "run").resolve()
    assert Path(resolved["artifact_dir"]) == (tmp_path / "drive-run").resolve()
    assert resolved["dataset_release"]["dataset_version"] == DEFAULT_DATASET_VERSION
    assert (
        resolved["dataset_release"]["dataset_fingerprint"]
        == DEFAULT_DATASET_FINGERPRINT
    )


def test_resume_config_fingerprint_allows_path_epoch_and_device_relocation():
    first = {
        "dataset_root": "/content/data",
        "output_dir": "/content/run",
        "artifact_dir": "/content/drive/run",
        "device": "cuda",
        "epochs": 30,
        "workers": 2,
        "batch_size": 4,
        "preprocess": {"input_width": 640, "input_height": 384},
    }
    relocated = {
        **first,
        "dataset_root": "D:/dataset",
        "output_dir": "D:/run",
        "artifact_dir": "G:/drive/run",
        "device": "cuda:0",
        "epochs": 60,
        "workers": 4,
    }
    changed_batch = {**relocated, "batch_size": 8}
    assert training_config_fingerprint(first) == training_config_fingerprint(relocated)
    assert training_config_fingerprint(first) != training_config_fingerprint(
        changed_batch
    )


def test_new_run_refuses_existing_local_or_drive_directory(tmp_path):
    output = tmp_path / "local-run"
    output.mkdir()
    config = {
        "output_dir": str(output),
        "artifact_dir": str(tmp_path / "drive-run"),
    }
    try:
        prepare_run_directories(config)
    except FileExistsError as exc:
        assert "output directory already exists" in str(exc)
    else:
        raise AssertionError("existing output directory was not rejected")
