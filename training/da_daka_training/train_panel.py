"""Train and evaluate the learned solar-panel object detector."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from da_daka_training.detection_metrics import evaluate_panel_detection
from da_daka_training.models import create_panel_model
from da_daka_training.torch_data import PanelCocoDataset, detection_collate
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
    train_dataset = PanelCocoDataset(dataset_root, 'train', config, augment=True)
    validation_dataset = PanelCocoDataset(
        dataset_root, 'validation', config, augment=False
    )
    loader = torch.utils.data.DataLoader(
        train_dataset,
        batch_size=int(config.get('batch_size', 2)),
        shuffle=True,
        num_workers=int(config.get('workers', 2)),
        collate_fn=detection_collate,
        generator=torch.Generator().manual_seed(seed),
    )
    model = create_panel_model(config).to(device)
    optimizer = torch.optim.SGD(
        [parameter for parameter in model.parameters() if parameter.requires_grad],
        lr=float(config.get('learning_rate', 0.005)),
        momentum=0.9,
        weight_decay=float(config.get('weight_decay', 0.0005)),
    )
    history = []
    for epoch in range(1, int(config.get('epochs', 30)) + 1):
        train_dataset.set_epoch(epoch)
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
        history.append({'epoch': epoch, 'train_loss': float(np.mean(losses))})
    metrics = _evaluate(model, validation_dataset, device, config)
    manifest = dataset_manifest(dataset_root)
    torch.save(
        {
            'task': 'panel_detection',
            'model_state': model.state_dict(),
            'config': config,
            'dataset_version': manifest['dataset_version'],
            'dataset_fingerprint': manifest['dataset_fingerprint'],
            'git_commit': git_commit(),
            'validation_metrics': metrics,
        },
        output / 'checkpoint.pt',
    )
    (output / 'training_history.json').write_text(
        json.dumps(history, indent=2) + '\n', encoding='utf-8'
    )
    (output / 'validation_metrics.json').write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + '\n', encoding='utf-8'
    )


def _evaluate(model, dataset, device, config):
    import torch

    score_threshold = float(config.get('evaluation_score_threshold', 0.05))
    model.eval()
    samples = []
    with torch.no_grad():
        for index, (image_info, panel_annotations) in enumerate(dataset.records):
            image, _boxes, transform = dataset.prepare_numpy(index, augment=False)
            output = model([torch.from_numpy(image).to(device)])[0]
            predictions = []
            for box, score, label in zip(
                output['boxes'].cpu().numpy(),
                output['scores'].cpu().numpy(),
                output['labels'].cpu().numpy(),
            ):
                if int(label) != 1 or float(score) < score_threshold:
                    continue
                x1, y1, x2, y2 = box
                original = transform.to_original_bbox((x1, y1, x2 - x1, y2 - y1))
                predictions.append({'bbox': original, 'score': float(score)})
            samples.append(
                {
                    'image_width': image_info['width'],
                    'image_height': image_info['height'],
                    'ground_truth': [
                        {'bbox': item['bbox']} for item in panel_annotations
                    ],
                    'predictions': predictions,
                }
            )
    return {
        'score_threshold': score_threshold,
        **evaluate_panel_detection(samples),
    }


if __name__ == '__main__':
    main()
