"""Safety-focused dirt segmentation metrics, including centroid error."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import cv2
import numpy as np


@dataclass(frozen=True)
class SegmentationMetrics:
    precision: float
    recall: float
    iou: float
    dice: float
    dirty_recall: float
    clean_specificity: float
    false_clean_rate: float
    false_dirty_rate: float
    small_dirt_recall: float
    mean_centroid_error_px: float
    mean_centroid_error_norm: float


def evaluate_segmentation(
    predictions: Iterable[np.ndarray],
    ground_truths: Iterable[np.ndarray],
    *,
    small_component_area_ratio: float = 0.002,
) -> SegmentationMetrics:
    """Evaluate pixel, sample-level safety and component/centroid behavior."""
    prediction_values = [np.asarray(value, dtype=bool) for value in predictions]
    truth_values = [np.asarray(value, dtype=bool) for value in ground_truths]
    if len(prediction_values) != len(truth_values):
        raise ValueError('prediction and ground truth counts must match')
    pairs = list(zip(prediction_values, truth_values))
    if not pairs:
        raise ValueError('at least one prediction/ground-truth pair is required')
    if any(pred.shape != truth.shape or pred.ndim != 2 for pred, truth in pairs):
        raise ValueError('prediction and ground truth masks must be paired 2D arrays')
    true_positive = false_positive = false_negative = 0
    dirty_total = clean_total = dirty_found = clean_correct = 0
    small_total = small_found = 0
    centroid_px = []
    centroid_norm = []
    for prediction, truth in pairs:
        true_positive += int(np.count_nonzero(prediction & truth))
        false_positive += int(np.count_nonzero(prediction & ~truth))
        false_negative += int(np.count_nonzero(~prediction & truth))
        actual_dirty = bool(np.any(truth))
        predicted_dirty = bool(np.any(prediction))
        if actual_dirty:
            dirty_total += 1
            dirty_found += int(predicted_dirty)
        else:
            clean_total += 1
            clean_correct += int(not predicted_dirty)
        truth_components = _components(truth)
        prediction_components = _components(prediction)
        for component in truth_components:
            if component['area_ratio'] <= small_component_area_ratio:
                small_total += 1
                small_found += int(
                    np.any(prediction & component['mask'])
                )
        height, width = truth.shape
        diagonal = math.hypot(width, height)
        for truth_component in truth_components:
            matched = max(
                prediction_components,
                key=lambda value: int(
                    np.count_nonzero(value['mask'] & truth_component['mask'])
                ),
                default=None,
            )
            overlap = 0 if matched is None else int(
                np.count_nonzero(matched['mask'] & truth_component['mask'])
            )
            if overlap:
                error = math.hypot(
                    matched['centroid'][0] - truth_component['centroid'][0],
                    matched['centroid'][1] - truth_component['centroid'][1],
                )
            else:
                # A missing or spatially unrelated spray target is the maximum
                # normalized miss, not a misleading zero-error observation.
                error = diagonal
            centroid_px.append(error)
            centroid_norm.append(error / diagonal)
    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    iou = _ratio(
        true_positive,
        true_positive + false_positive + false_negative,
    )
    dice = _ratio(2 * true_positive, 2 * true_positive + false_positive + false_negative)
    dirty_recall = _ratio(dirty_found, dirty_total)
    clean_specificity = _ratio(clean_correct, clean_total)
    return SegmentationMetrics(
        precision=precision,
        recall=recall,
        iou=iou,
        dice=dice,
        dirty_recall=dirty_recall,
        clean_specificity=clean_specificity,
        false_clean_rate=1.0 - dirty_recall if dirty_total else 0.0,
        false_dirty_rate=1.0 - clean_specificity if clean_total else 0.0,
        small_dirt_recall=_ratio(small_found, small_total),
        mean_centroid_error_px=float(np.mean(centroid_px)) if centroid_px else 0.0,
        mean_centroid_error_norm=float(np.mean(centroid_norm)) if centroid_norm else 0.0,
    )


def _components(mask: np.ndarray):
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8),
        connectivity=8,
    )
    values = []
    for component_id in range(1, count):
        component = labels == component_id
        area = int(stats[component_id, cv2.CC_STAT_AREA])
        values.append(
            {
                'mask': component,
                'area': area,
                'area_ratio': area / mask.size,
                'centroid': _centroid(component),
            }
        )
    return values


def _centroid(mask: np.ndarray) -> tuple[float, float]:
    ys, xs = np.nonzero(mask)
    return float(xs.mean()), float(ys.mean())


def _ratio(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 0.0
