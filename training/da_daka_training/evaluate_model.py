"""Evaluate a checkpoint on an explicitly selected locked dataset split."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from da_daka_training.models import create_dirt_model, create_panel_model
from da_daka_training.release import verify_dataset_release
from da_daka_training.torch_data import DirtRoiDataset, PanelCocoDataset
from da_daka_training.train_common import choose_device
from da_daka_training.train_dirt import _evaluate as evaluate_dirt
from da_daka_training.train_panel import _evaluate as evaluate_panel


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--split", choices=("validation", "test"), required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dataset-root")
    parser.add_argument("--device", default=None)
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--score-threshold", type=float, default=None)
    args = parser.parse_args()

    import torch

    checkpoint = torch.load(
        args.checkpoint,
        map_location="cpu",
        weights_only=False,
    )
    task = checkpoint.get("task")
    config = dict(checkpoint["config"])
    config["pretrained"] = False
    dataset_root = (
        Path(
            args.dataset_root
            or os.environ.get("DA_DAKA_DATASET_ROOT")
            or config["dataset_root"]
        )
        .expanduser()
        .resolve()
    )
    config["dataset_root"] = str(dataset_root)
    output = Path(args.output_dir).resolve()
    device = choose_device(args.device or str(config.get("device", "cuda")))
    verify_dataset_release(
        dataset_root,
        expected_version=checkpoint["dataset_version"],
        expected_fingerprint=checkpoint["dataset_fingerprint"],
        mode="full",
    )
    output.mkdir(parents=True, exist_ok=False)

    if task == "dirt_segmentation":
        if args.threshold is None:
            raise ValueError("--threshold is required for locked dirt evaluation")
        model = create_dirt_model(config)
        dataset = DirtRoiDataset(
            dataset_root,
            args.split,
            config,
            augment=False,
        )
        model.load_state_dict(checkpoint["model_state"])
        metrics = evaluate_dirt(
            model.to(device),
            dataset,
            device,
            threshold=args.threshold,
            predictions_directory=output / "probabilities",
        )
        metrics["threshold_status"] = "EXPLICIT_LOCKED_EVALUATION_INPUT"
    elif task == "panel_detection":
        if args.threshold is not None:
            raise ValueError("--threshold applies only to dirt segmentation")
        if args.score_threshold is not None:
            config["evaluation_score_threshold"] = float(args.score_threshold)
        model = create_panel_model(config)
        dataset = PanelCocoDataset(
            dataset_root,
            args.split,
            config,
            augment=False,
        )
        model.load_state_dict(checkpoint["model_state"])
        metrics = evaluate_panel(model.to(device), dataset, device, config)
    else:
        raise ValueError(f"unsupported checkpoint task: {task!r}")

    report = {
        "task": task,
        "split": args.split,
        "dataset_version": checkpoint["dataset_version"],
        "dataset_fingerprint": checkpoint["dataset_fingerprint"],
        "checkpoint_git_commit": checkpoint["git_commit"],
        "metrics": metrics,
    }
    (output / "evaluation.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
