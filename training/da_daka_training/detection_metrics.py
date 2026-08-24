"""Framework-neutral single-class panel detection evaluation."""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence


def evaluate_panel_detection(
    samples: Iterable[Mapping],
    *,
    iou_thresholds: Sequence[float] = tuple(value / 100 for value in range(50, 100, 5)),
) -> dict[str, float]:
    """Report precision/recall/AP and partial/small panel recall."""
    values = list(samples)
    if not values:
        raise ValueError('panel evaluation needs samples')
    threshold_reports = [
        _evaluate_at_threshold(values, threshold) for threshold in iou_thresholds
    ]
    at_50 = threshold_reports[0]
    partial_total = partial_found = small_total = small_found = 0
    for sample in values:
        width = float(sample['image_width'])
        height = float(sample['image_height'])
        predictions = sample.get('predictions', [])
        for truth in sample.get('ground_truth', []):
            box = truth['bbox']
            matched = any(_iou(box, item['bbox']) >= 0.5 for item in predictions)
            x, y, box_width, box_height = box
            if x <= 0.0 or y <= 0.0 or x + box_width >= width or y + box_height >= height:
                partial_total += 1
                partial_found += int(matched)
            if box_width * box_height / (width * height) <= 0.02:
                small_total += 1
                small_found += int(matched)
    return {
        'precision_iou50': at_50['precision'],
        'recall_iou50': at_50['recall'],
        'map_50_95': sum(item['ap'] for item in threshold_reports) / len(threshold_reports),
        'partial_panel_recall': _ratio(partial_found, partial_total),
        'small_distant_panel_recall': _ratio(small_found, small_total),
    }


def _evaluate_at_threshold(samples, threshold):
    ranked = []
    total_truth = sum(len(sample.get('ground_truth', [])) for sample in samples)
    for sample_index, sample in enumerate(samples):
        for prediction in sample.get('predictions', []):
            ranked.append((float(prediction['score']), sample_index, prediction['bbox']))
    ranked.sort(key=lambda item: -item[0])
    used = {index: set() for index in range(len(samples))}
    true_positive = []
    false_positive = []
    for _score, sample_index, box in ranked:
        truths = samples[sample_index].get('ground_truth', [])
        best = max(
            (
                (_iou(box, truth['bbox']), truth_index)
                for truth_index, truth in enumerate(truths)
                if truth_index not in used[sample_index]
            ),
            default=(0.0, -1),
        )
        matched = best[0] >= threshold
        if matched:
            used[sample_index].add(best[1])
        true_positive.append(int(matched))
        false_positive.append(int(not matched))
    cumulative_tp = 0
    cumulative_fp = 0
    precisions = []
    recalls = []
    for tp, fp in zip(true_positive, false_positive):
        cumulative_tp += tp
        cumulative_fp += fp
        precisions.append(_ratio(cumulative_tp, cumulative_tp + cumulative_fp))
        recalls.append(_ratio(cumulative_tp, total_truth))
    ap = 0.0
    for recall_level in [value / 100 for value in range(101)]:
        ap += max(
            (
                precision for precision, recall in zip(precisions, recalls)
                if recall >= recall_level
            ),
            default=0.0,
        ) / 101.0
    return {
        'precision': precisions[-1] if precisions else 0.0,
        'recall': recalls[-1] if recalls else 0.0,
        'ap': ap,
    }


def _iou(left, right):
    lx, ly, lw, lh = (float(value) for value in left)
    rx, ry, rw, rh = (float(value) for value in right)
    width = max(0.0, min(lx + lw, rx + rw) - max(lx, rx))
    height = max(0.0, min(ly + lh, ry + rh) - max(ly, ry))
    intersection = width * height
    union = lw * lh + rw * rh - intersection
    return intersection / union if union > 0.0 else 0.0


def _ratio(numerator, denominator):
    return float(numerator / denominator) if denominator else 0.0
