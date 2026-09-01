"""CPU-only trainer orchestration tests; CI skips when torch is intentionally absent."""

import json
import sys

import cv2
import numpy as np
import pytest
import yaml

torch = pytest.importorskip("torch")

from da_daka_training import train_dirt, train_panel  # noqa: E402
from da_daka_training.dataset_builder import build_master_dataset  # noqa: E402
from da_daka_training.loader_smoke import loader_smoke_test  # noqa: E402


def _source(root, value, *, dirty=False):
    root.mkdir()
    (root / "images/default").mkdir(parents=True)
    image = np.full((40, 60, 3), value, dtype=np.uint8)
    assert cv2.imwrite(str(root / "images/default/frame.png"), image)
    annotations = [
        {
            "id": 1,
            "image_id": 1,
            "category_id": 1,
            "bbox": [5, 5, 50, 30],
            "area": 1500,
            "segmentation": [],
            "iscrowd": 0,
        }
    ]
    if dirty:
        annotations.append(
            {
                "id": 2,
                "image_id": 1,
                "category_id": 2,
                "bbox": [12, 12, 8, 8],
                "area": 64,
                "segmentation": [[12, 12, 20, 12, 20, 20, 12, 20]],
                "iscrowd": 0,
            }
        )
    coco = {
        "images": [{"id": 1, "file_name": "frame.png", "width": 60, "height": 40}],
        "annotations": annotations,
        "categories": [
            {"id": 1, "name": "solar_panel"},
            {"id": 2, "name": "dirt"},
        ],
    }
    (root / "annotations").mkdir()
    (root / "annotations/instances_default.json").write_text(json.dumps(coco))
    return root


def _release(tmp_path):
    sources = [
        _source(tmp_path / "source-1", 30),
        _source(tmp_path / "source-2", 90, dirty=True),
        _source(tmp_path / "source-3", 150),
    ]
    output = build_master_dataset(
        {
            "output_dir": str(tmp_path / "dataset"),
            "sources": [
                {
                    "path": str(path),
                    "source_task": f"task-{index}",
                    "capture_session": f"session-{index}",
                }
                for index, path in enumerate(sources, 1)
            ],
            "split": {"seed": "entrypoint-test", "ratios": [0.7, 0.15, 0.15]},
        }
    )
    manifest = json.loads((output / "dataset_manifest.json").read_text())
    return output, manifest


def _config(path, dataset, output, artifact, manifest, *, task, epochs=1):
    value = {
        "dataset_root": str(dataset),
        "output_dir": str(output),
        "artifact_dir": str(artifact),
        "device": "cpu",
        "dataset_release": {
            "dataset_version": manifest["dataset_version"],
            "dataset_fingerprint": manifest["dataset_fingerprint"],
            "verification_mode": "full",
        },
        "seed": 7,
        "deterministic": True,
        "pretrained": False,
        "epochs": epochs,
        "batch_size": 1,
        "workers": 0,
        "learning_rate": 0.01,
        "weight_decay": 0.0,
        "preprocess": {
            "input_width": 64,
            "input_height": 64,
            "padding_value": 0,
            "color": "RGB",
            "scale": 1 / 255,
            "mean": [0, 0, 0],
            "std": [1, 1, 1],
        },
        "augmentation": {},
        "postprocess": {
            "minimum_component_area": 0,
            "minimum_component_area_ratio": 0,
        },
    }
    if task == "panel":
        value.update(
            {
                "checkpoint_selection_metric": "map_50_95",
                "evaluation_score_threshold": 0.05,
            }
        )
    else:
        value.update(
            {
                "checkpoint_selection_metric": "dice",
                "evaluation_threshold_placeholder": 0.5,
            }
        )
    path.write_text(yaml.safe_dump(value), encoding="utf-8")
    return path


class _ToyPanel(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.weight = torch.nn.Parameter(torch.tensor(1.0))

    def forward(self, images, targets=None):
        if self.training and targets is not None:
            return {"loss": self.weight.square()}
        return [
            {
                "boxes": torch.tensor([[5.0, 5.0, 55.0, 35.0]], device=image.device),
                "scores": torch.tensor([0.9], device=image.device),
                "labels": torch.tensor([1], device=image.device),
            }
            for image in images
        ]


class _ToyDirt(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.weight = torch.nn.Parameter(torch.tensor(0.2))

    def forward(self, images):
        foreground = self.weight.expand(
            images.shape[0], 1, images.shape[2], images.shape[3]
        )
        return {"out": torch.cat((-foreground, foreground), dim=1)}


def test_real_panel_and_dirt_dataloaders_smoke_every_split(tmp_path):
    dataset, manifest = _release(tmp_path)
    panel_path = _config(
        tmp_path / "panel.yaml",
        dataset,
        tmp_path / "unused-panel-local",
        tmp_path / "unused-panel-drive",
        manifest,
        task="panel",
    )
    dirt_path = _config(
        tmp_path / "dirt.yaml",
        dataset,
        tmp_path / "unused-dirt-local",
        tmp_path / "unused-dirt-drive",
        manifest,
        task="dirt",
    )
    report = loader_smoke_test(
        dataset,
        panel_config=yaml.safe_load(panel_path.read_text()),
        dirt_config=yaml.safe_load(dirt_path.read_text()),
        expected_version=manifest["dataset_version"],
        expected_fingerprint=manifest["dataset_fingerprint"],
    )
    assert report["status"] == "LOADERS_READY"
    assert set(report["loaders"]["panel_detection"]) == {
        "train",
        "validation",
        "test",
    }


def test_panel_trainer_writes_best_last_metadata_and_drive_mirror(
    tmp_path, monkeypatch
):
    dataset, manifest = _release(tmp_path)
    config = _config(
        tmp_path / "panel.yaml",
        dataset,
        tmp_path / "panel-local",
        tmp_path / "panel-drive",
        manifest,
        task="panel",
    )
    monkeypatch.setattr(train_panel, "create_panel_model", lambda _config: _ToyPanel())
    monkeypatch.setattr(sys, "argv", ["da-daka-train-panel", "--config", str(config)])
    train_panel.main()
    for relative in (
        "checkpoints/last.pt",
        "checkpoints/best.pt",
        "checkpoint.pt",
        "training_history.json",
        "validation_metrics.json",
        "run_metadata.json",
    ):
        assert (tmp_path / "panel-local" / relative).is_file()
        assert (tmp_path / "panel-drive" / relative).is_file()
    metadata = json.loads((tmp_path / "panel-drive/run_metadata.json").read_text())
    assert metadata["status"] == "COMPLETED"


def test_dirt_trainer_resume_restores_epoch_and_mirrors_probability_archive(
    tmp_path, monkeypatch
):
    dataset, manifest = _release(tmp_path)
    artifact = tmp_path / "dirt-drive"
    first_config = _config(
        tmp_path / "dirt-1.yaml",
        dataset,
        tmp_path / "dirt-local-1",
        artifact,
        manifest,
        task="dirt",
        epochs=1,
    )
    monkeypatch.setattr(train_dirt, "create_dirt_model", lambda _config: _ToyDirt())
    monkeypatch.setattr(
        sys, "argv", ["da-daka-train-dirt", "--config", str(first_config)]
    )
    train_dirt.main()
    assert (artifact / "validation_probabilities.zip").is_file()

    second_config = _config(
        tmp_path / "dirt-2.yaml",
        dataset,
        tmp_path / "dirt-local-2",
        artifact,
        manifest,
        task="dirt",
        epochs=2,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "da-daka-train-dirt",
            "--config",
            str(second_config),
            "--resume",
            str(artifact / "checkpoints/last.pt"),
        ],
    )
    train_dirt.main()
    checkpoint = torch.load(
        artifact / "checkpoints/last.pt", map_location="cpu", weights_only=False
    )
    assert checkpoint["epoch"] == 2
    assert len(checkpoint["history"]) == 2
