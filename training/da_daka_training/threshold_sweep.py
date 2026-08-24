"""Sweep segmentation thresholds with false-clean risk made explicit."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

import cv2
import numpy as np

from da_daka_training.metrics import evaluate_segmentation
from laptop_ai.segmentation_postprocess import connected_components


def threshold_sweep(
    probabilities: list[np.ndarray],
    ground_truths: list[np.ndarray],
    thresholds: list[float],
    *,
    minimum_component_area: int = 0,
    minimum_component_area_ratio: float = 0.0,
) -> list[dict]:
    reports = []
    for threshold in thresholds:
        metrics = evaluate_segmentation(
            [
                connected_components(
                    probability,
                    threshold=threshold,
                    minimum_component_area=minimum_component_area,
                    minimum_component_area_ratio=minimum_component_area_ratio,
                )[0] > 0
                for probability in probabilities
            ],
            ground_truths,
        )
        reports.append({'threshold': threshold, **asdict(metrics)})
    return reports


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset-root', required=True)
    parser.add_argument('--predictions-dir', required=True)
    parser.add_argument('--start', type=float, default=0.05)
    parser.add_argument('--stop', type=float, default=0.95)
    parser.add_argument('--step', type=float, default=0.05)
    parser.add_argument('--minimum-component-area', type=int, default=0)
    parser.add_argument('--minimum-component-area-ratio', type=float, default=0.0)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(args.dataset_root)
    samples = [
        json.loads(line) for line in
        (root / 'dirt_segmentation/samples.jsonl').read_text(encoding='utf-8').splitlines()
        if line.strip() and json.loads(line)['split'] == 'validation'
    ]
    probabilities = []
    ground_truths = []
    for sample in samples:
        probability = np.load(Path(args.predictions_dir) / f'{sample["sample_id"]}.npy')
        truth = cv2.imread(
            str(root / 'dirt_segmentation' / sample['mask']),
            cv2.IMREAD_GRAYSCALE,
        ) > 0
        if probability.shape != truth.shape:
            raise ValueError(f'prediction shape mismatch for {sample["sample_id"]}')
        probabilities.append(probability)
        ground_truths.append(truth)
    thresholds = list(np.arange(args.start, args.stop + args.step / 2, args.step))
    results = threshold_sweep(
        probabilities,
        ground_truths,
        thresholds,
        minimum_component_area=args.minimum_component_area,
        minimum_component_area_ratio=args.minimum_component_area_ratio,
    )
    report = {
        'selection_status': 'UNSELECTED_REQUIRES_PROJECT_RISK_REVIEW',
        'primary_risk': 'false_clean_rate',
        'validation_sample_count': len(samples),
        'minimum_component_area': args.minimum_component_area,
        'minimum_component_area_ratio': args.minimum_component_area_ratio,
        'results': results,
    }
    Path(args.output).write_text(
        json.dumps(report, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )


if __name__ == '__main__':
    main()
