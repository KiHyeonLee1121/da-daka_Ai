"""Train and evaluate the learned solar-panel object detector."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from da_daka_training.detection_metrics import evaluate_panel_detection
from da_daka_training.models import create_panel_model
from da_daka_training.torch_data import PanelCocoDataset, detection_collate
from da_daka_training.train_common import (
    add_training_arguments,
    checkpoint_payload,
    choose_device,
    copy_resume_best_checkpoint,
    create_run_metadata,
    dataset_manifest,
    finish_run_metadata,
    mirror_artifacts,
    prepare_run_directories,
    resolve_training_config,
    resume_training,
    save_checkpoint,
    seed_training,
    verify_training_dataset,
    write_json,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    add_training_arguments(parser)
    args = parser.parse_args()

    import torch

    config = resolve_training_config(args)
    device = choose_device(str(config.get("device", "cuda")))
    release_report = verify_training_dataset(config)
    seed = seed_training(
        config.get("seed", 20260825),
        deterministic=bool(config.get("deterministic", True)),
    )
    dataset_root = Path(config["dataset_root"]).resolve()
    output, artifact = prepare_run_directories(config, resume_path=args.resume)
    train_dataset = PanelCocoDataset(dataset_root, "train", config, augment=True)
    validation_dataset = PanelCocoDataset(
        dataset_root, "validation", config, augment=False
    )
    model = create_panel_model(config).to(device)
    optimizer = torch.optim.SGD(
        [parameter for parameter in model.parameters() if parameter.requires_grad],
        lr=float(config.get("learning_rate", 0.005)),
        momentum=0.9,
        weight_decay=float(config.get("weight_decay", 0.0005)),
    )
    manifest = dataset_manifest(dataset_root)
    start_epoch, history, best_metric, best_epoch, resumed_run_id = resume_training(
        args.resume,
        task="panel_detection",
        config=config,
        model=model,
        optimizer=optimizer,
    )
    copy_resume_best_checkpoint(
        args.resume,
        output,
        task="panel_detection",
        config=config,
    )
    metadata = create_run_metadata(
        "panel_detection",
        config,
        release_report,
        resume_path=args.resume,
        run_id=resumed_run_id,
    )
    write_json(output / "run_metadata.json", metadata)
    mirror_artifacts(output, artifact, ["run_metadata.json"])
    epochs = int(config.get("epochs", 30))
    selection_metric = str(config.get("checkpoint_selection_metric", "map_50_95"))
    for epoch in range(start_epoch, epochs + 1):
        train_dataset.set_epoch(epoch)
        loader = torch.utils.data.DataLoader(
            train_dataset,
            batch_size=int(config.get("batch_size", 2)),
            shuffle=True,
            num_workers=int(config.get("workers", 2)),
            collate_fn=detection_collate,
            generator=torch.Generator().manual_seed(seed + epoch),
        )
        model.train()
        losses = []
        for images, targets in loader:
            images = [image.to(device) for image in images]
            targets = [
                {key: value.to(device) for key, value in target.items()}
                for target in targets
            ]
            optimizer.zero_grad(set_to_none=True)
            loss_map = model(images, targets)
            loss = sum(loss_map.values())
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        metrics = _evaluate(model, validation_dataset, device, config)
        if selection_metric not in metrics:
            raise ValueError(
                f"unknown panel checkpoint selection metric: {selection_metric}"
            )
        metric = float(metrics[selection_metric])
        is_best = metric > best_metric
        if is_best:
            best_metric = metric
            best_epoch = epoch
        history.append(
            {
                "epoch": epoch,
                "train_loss": float(np.mean(losses)),
                "validation_metrics": metrics,
            }
        )
        payload = checkpoint_payload(
            task="panel_detection",
            model=model,
            optimizer=optimizer,
            config=config,
            manifest=manifest,
            epoch=epoch,
            history=history,
            best_metric=best_metric,
            best_epoch=best_epoch,
            run_id=metadata["run_id"],
            validation_metrics=metrics,
        )
        save_checkpoint(output / "checkpoints/last.pt", payload)
        if is_best:
            save_checkpoint(output / "checkpoints/best.pt", payload)
        write_json(output / "training_history.json", history)
        mirror_artifacts(
            output,
            artifact,
            [
                "run_metadata.json",
                "training_history.json",
                "checkpoints/last.pt",
                "checkpoints/best.pt",
            ],
        )

    best_checkpoint = torch.load(
        output / "checkpoints/best.pt", map_location="cpu", weights_only=False
    )
    model.load_state_dict(best_checkpoint["model_state"])
    metrics = _evaluate(model, validation_dataset, device, config)
    save_checkpoint(output / "checkpoint.pt", best_checkpoint)
    write_json(output / "validation_metrics.json", metrics)
    metadata = finish_run_metadata(
        metadata, best_epoch=best_epoch, best_metric=best_metric
    )
    write_json(output / "run_metadata.json", metadata)
    mirror_artifacts(
        output,
        artifact,
        [
            "run_metadata.json",
            "training_history.json",
            "validation_metrics.json",
            "checkpoint.pt",
            "checkpoints/last.pt",
            "checkpoints/best.pt",
        ],
    )


def _evaluate(model, dataset, device, config):
    import torch

    score_threshold = float(config.get("evaluation_score_threshold", 0.05))
    model.eval()
    samples = []
    with torch.no_grad():
        for index, (image_info, panel_annotations) in enumerate(dataset.records):
            image, _boxes, transform = dataset.prepare_numpy(index, augment=False)
            output = model([torch.from_numpy(image).to(device)])[0]
            predictions = []
            for box, score, label in zip(
                output["boxes"].cpu().numpy(),
                output["scores"].cpu().numpy(),
                output["labels"].cpu().numpy(),
            ):
                if int(label) != 1 or float(score) < score_threshold:
                    continue
                x1, y1, x2, y2 = box
                original = transform.to_original_bbox((x1, y1, x2 - x1, y2 - y1))
                predictions.append({"bbox": original, "score": float(score)})
            samples.append(
                {
                    "image_width": image_info["width"],
                    "image_height": image_info["height"],
                    "ground_truth": [
                        {"bbox": item["bbox"]} for item in panel_annotations
                    ],
                    "predictions": predictions,
                }
            )
    return {
        "score_threshold": score_threshold,
        **evaluate_panel_detection(samples),
    }


if __name__ == "__main__":
    main()
