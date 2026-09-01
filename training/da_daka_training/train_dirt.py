"""Train and validate the panel-ROI binary dirt segmenter."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

import numpy as np

from da_daka_training.metrics import evaluate_segmentation
from da_daka_training.models import create_dirt_model
from da_daka_training.torch_data import DirtRoiDataset
from da_daka_training.train_common import (
    add_training_arguments,
    archive_directory,
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
    train_dataset = DirtRoiDataset(dataset_root, "train", config, augment=True)
    validation_dataset = DirtRoiDataset(
        dataset_root, "validation", config, augment=False
    )
    model = create_dirt_model(config).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(config.get("learning_rate", 1e-4)),
        weight_decay=float(config.get("weight_decay", 1e-4)),
    )
    manifest = dataset_manifest(dataset_root)
    start_epoch, history, best_metric, best_epoch, resumed_run_id = resume_training(
        args.resume,
        task="dirt_segmentation",
        config=config,
        model=model,
        optimizer=optimizer,
    )
    copy_resume_best_checkpoint(
        args.resume,
        output,
        task="dirt_segmentation",
        config=config,
    )
    metadata = create_run_metadata(
        "dirt_segmentation",
        config,
        release_report,
        resume_path=args.resume,
        run_id=resumed_run_id,
    )
    write_json(output / "run_metadata.json", metadata)
    mirror_artifacts(output, artifact, ["run_metadata.json"])
    epochs = int(config.get("epochs", 30))
    selection_metric = str(config.get("checkpoint_selection_metric", "dice"))
    for epoch in range(start_epoch, epochs + 1):
        train_dataset.set_epoch(epoch)
        loader = torch.utils.data.DataLoader(
            train_dataset,
            batch_size=int(config.get("batch_size", 4)),
            shuffle=True,
            num_workers=int(config.get("workers", 2)),
            generator=torch.Generator().manual_seed(seed + epoch),
        )
        model.train()
        losses = []
        for images, masks in loader:
            images = images.to(device)
            masks = masks.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(images)["out"]
            loss = torch.nn.functional.cross_entropy(logits, masks)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        metrics = _evaluate(model, validation_dataset, device)
        if selection_metric not in metrics:
            raise ValueError(
                f"unknown dirt checkpoint selection metric: {selection_metric}"
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
            task="dirt_segmentation",
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
    metrics = _evaluate(
        model,
        validation_dataset,
        device,
        predictions_directory=output / "validation_probabilities",
    )
    archive_directory(
        output / "validation_probabilities",
        output / "validation_probabilities.zip",
    )
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
            "validation_probabilities.zip",
            "checkpoint.pt",
            "checkpoints/last.pt",
            "checkpoints/best.pt",
        ],
    )


def _evaluate(
    model,
    dataset,
    device,
    *,
    threshold=None,
    predictions_directory=None,
):
    import torch
    from laptop_ai.preprocessing import inverse_letterbox_map
    from laptop_ai.segmentation_postprocess import connected_components

    model.eval()
    predictions = []
    truths = []
    threshold = float(
        dataset.config.get("evaluation_threshold_placeholder", 0.5)
        if threshold is None
        else threshold
    )
    if not 0.0 < threshold < 1.0:
        raise ValueError("evaluation threshold must be within (0, 1)")
    if predictions_directory is not None:
        predictions_directory = Path(predictions_directory)
        predictions_directory.mkdir(parents=True, exist_ok=False)
    postprocess = dataset.config.get("postprocess", {})
    minimum_component_area = int(postprocess.get("minimum_component_area", 0))
    minimum_component_area_ratio = float(
        postprocess.get("minimum_component_area_ratio", 0.0)
    )
    with torch.no_grad():
        for index in range(len(dataset)):
            image, _padded_mask, original_mask, transform = dataset.prepare_numpy(
                index,
                augment=False,
            )
            logits = model(torch.from_numpy(image[None]).to(device))["out"]
            probability = torch.softmax(logits, dim=1)[0, 1].cpu().numpy()
            original_probability = inverse_letterbox_map(probability, transform)
            if predictions_directory is not None:
                np.save(
                    predictions_directory
                    / f"{dataset.samples[index]['sample_id']}.npy",
                    original_probability.astype(np.float32),
                )
            filtered_mask, _components = connected_components(
                original_probability,
                threshold=threshold,
                minimum_component_area=minimum_component_area,
                minimum_component_area_ratio=minimum_component_area_ratio,
            )
            predictions.append(filtered_mask > 0)
            truths.append(original_mask)
    return {
        "threshold": threshold,
        "threshold_status": "PLACEHOLDER_REQUIRES_SWEEP",
        "minimum_component_area": minimum_component_area,
        "minimum_component_area_ratio": minimum_component_area_ratio,
        **asdict(evaluate_segmentation(predictions, truths)),
    }


if __name__ == "__main__":
    main()
