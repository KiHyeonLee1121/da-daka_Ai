"""Analyze real panel ROI geometry before choosing model input dimensions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
import yaml

from da_daka_training.release import (
    DEFAULT_DATASET_FINGERPRINT,
    DEFAULT_DATASET_VERSION,
    verify_dataset_release,
)


def analyze_dataset(
    dataset_root: str | Path,
    candidates: Iterable[tuple[int, int]],
) -> dict:
    root = Path(dataset_root)
    samples = [
        json.loads(line) for line in
        (root / 'dirt_segmentation/samples.jsonl').read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    if not samples:
        raise ValueError('dirt segmentation dataset has no ROI samples')
    widths = np.asarray([item['width'] for item in samples], dtype=np.float64)
    heights = np.asarray([item['height'] for item in samples], dtype=np.float64)
    aspect_ratios = widths / heights
    dirt_ratios = np.asarray([item['dirt_area_ratio'] for item in samples], dtype=np.float64)
    component_areas = []
    for sample in samples:
        mask = cv2.imread(
            str(root / 'dirt_segmentation' / sample['mask']),
            cv2.IMREAD_GRAYSCALE,
        )
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
            (mask > 0).astype(np.uint8),
            connectivity=8,
        )
        component_areas.extend(
            int(stats[index, cv2.CC_STAT_AREA]) for index in range(1, count)
        )
    report = {
        'sample_count': len(samples),
        'clean_count': sum(item['clean_dirty'] == 'clean' for item in samples),
        'dirty_count': sum(item['clean_dirty'] == 'dirty' for item in samples),
        'roi_width_px': _distribution(widths),
        'roi_height_px': _distribution(heights),
        'roi_aspect_ratio': _distribution(aspect_ratios),
        'dirt_area_ratio': _distribution(dirt_ratios),
        'dirt_component_area_px': _distribution(np.asarray(component_areas, dtype=np.float64)),
        'input_candidates': [],
    }
    for width, height in candidates:
        scale = np.minimum(width / widths, height / heights)
        resized_width = widths * scale
        resized_height = heights * scale
        padding_ratio = 1.0 - (resized_width * resized_height) / (width * height)
        report['input_candidates'].append(
            {
                'width': int(width),
                'height': int(height),
                'median_scale': float(np.median(scale)),
                'p05_scale': float(np.quantile(scale, 0.05)),
                'median_padding_ratio': float(np.median(padding_ratio)),
                'p95_padding_ratio': float(np.quantile(padding_ratio, 0.95)),
                'requires_validation_accuracy_and_latency_benchmark': True,
            }
        )
    return report


def _distribution(values: np.ndarray) -> dict[str, float | None]:
    if values.size == 0:
        return {key: None for key in ('min', 'p05', 'median', 'p95', 'max')}
    return {
        'min': float(values.min()),
        'p05': float(np.quantile(values, 0.05)),
        'median': float(np.median(values)),
        'p95': float(np.quantile(values, 0.95)),
        'max': float(values.max()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset-root', required=True)
    parser.add_argument('--candidates', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--expected-version', default=DEFAULT_DATASET_VERSION)
    parser.add_argument('--expected-fingerprint', default=DEFAULT_DATASET_FINGERPRINT)
    args = parser.parse_args()
    verify_dataset_release(
        args.dataset_root,
        expected_version=args.expected_version,
        expected_fingerprint=args.expected_fingerprint,
        mode='full',
    )
    raw = yaml.safe_load(Path(args.candidates).read_text(encoding='utf-8'))
    candidates = [
        (int(item['width']), int(item['height']))
        for item in raw['candidates']
    ]
    report = analyze_dataset(args.dataset_root, candidates)
    Path(args.output).write_text(
        json.dumps(report, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )


if __name__ == '__main__':
    main()
