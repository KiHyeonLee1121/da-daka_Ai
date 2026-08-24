"""Train and validate the panel-ROI binary dirt segmenter."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

import numpy as np

from da_daka_training.metrics import evaluate_segmentation
from da_daka_training.models import create_dirt_model
from da_daka_training.torch_data import DirtRoiDataset
from da_daka_training.train_common import (
    choose_device,
    dataset_manifest,
    git_commit,
    load_config,
    seed_training,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()

    import torch
    config = load_config(args.config)
    seed = seed_training(
        config.get('seed', 20260825),
        deterministic=bool(config.get('deterministic', True)),
    )
    dataset_root = Path(config['dataset_root']).resolve()
    output = Path(config['output_dir']).resolve()
    output.mkdir(parents=True, exist_ok=False)
    device = choose_device(str(config.get('device', 'cuda')))
    train_dataset = DirtRoiDataset(
        dataset_root, 'train', config, augment=True
    )
    validation_dataset = DirtRoiDataset(
        dataset_root, 'validation', config, augment=False
    )
    loader = torch.utils.data.DataLoader(
        train_dataset,
        batch_size=int(config.get('batch_size', 4)),
        shuffle=True,
        num_workers=int(config.get('workers', 2)),
        generator=torch.Generator().manual_seed(seed),
    )
    model = create_dirt_model(config).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(config.get('learning_rate', 1e-4)),
        weight_decay=float(config.get('weight_decay', 1e-4)),
    )
    history = []
    for epoch in range(1, int(config.get('epochs', 30)) + 1):
        train_dataset.set_epoch(epoch)
        model.train()
        losses = []
        for images, masks in loader:
            images = images.to(device)
            masks = masks.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(images)['out']
            loss = torch.nn.functional.cross_entropy(logits, masks)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        history.append({'epoch': epoch, 'train_loss': float(np.mean(losses))})
    metrics = _evaluate(
        model,
        validation_dataset,
        device,
        predictions_directory=output / 'validation_probabilities',
    )
    manifest = dataset_manifest(dataset_root)
    checkpoint = {
        'task': 'dirt_segmentation',
        'model_state': model.state_dict(),
        'config': config,
        'dataset_version': manifest['dataset_version'],
        'dataset_fingerprint': manifest['dataset_fingerprint'],
        'git_commit': git_commit(),
        'validation_metrics_at_placeholder_threshold': metrics,
    }
    torch.save(checkpoint, output / 'checkpoint.pt')
    (output / 'training_history.json').write_text(
        json.dumps(history, indent=2) + '\n', encoding='utf-8'
    )
    (output / 'validation_metrics.json').write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + '\n', encoding='utf-8'
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
        dataset.config.get('evaluation_threshold_placeholder', 0.5)
        if threshold is None else threshold
    )
    if not 0.0 < threshold < 1.0:
        raise ValueError('evaluation threshold must be within (0, 1)')
    if predictions_directory is not None:
        predictions_directory = Path(predictions_directory)
        predictions_directory.mkdir(parents=True, exist_ok=False)
    postprocess = dataset.config.get('postprocess', {})
    minimum_component_area = int(
        postprocess.get('minimum_component_area', 0)
    )
    minimum_component_area_ratio = float(
        postprocess.get('minimum_component_area_ratio', 0.0)
    )
    with torch.no_grad():
        for index in range(len(dataset)):
            image, _padded_mask, original_mask, transform = dataset.prepare_numpy(
                index,
                augment=False,
            )
            logits = model(torch.from_numpy(image[None]).to(device))['out']
            probability = torch.softmax(logits, dim=1)[0, 1].cpu().numpy()
            original_probability = inverse_letterbox_map(probability, transform)
            if predictions_directory is not None:
                np.save(
                    predictions_directory
                    / f'{dataset.samples[index]["sample_id"]}.npy',
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
        'threshold': threshold,
        'threshold_status': 'PLACEHOLDER_REQUIRES_SWEEP',
        'minimum_component_area': minimum_component_area,
        'minimum_component_area_ratio': minimum_component_area_ratio,
        **asdict(evaluate_segmentation(predictions, truths)),
    }


if __name__ == '__main__':
    main()
