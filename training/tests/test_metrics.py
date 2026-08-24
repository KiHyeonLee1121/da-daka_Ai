import numpy as np
import pytest

from da_daka_training.detection_metrics import evaluate_panel_detection
from da_daka_training.augmentation import augment_image_mask
from da_daka_training.metrics import evaluate_segmentation
from da_daka_training.threshold_sweep import threshold_sweep


def test_segmentation_reports_false_clean_false_dirty_and_centroid_error():
    dirty_truth = np.zeros((20, 30), dtype=bool)
    dirty_truth[4:8, 5:9] = True
    shifted_prediction = np.zeros_like(dirty_truth)
    shifted_prediction[5:9, 6:10] = True
    clean = np.zeros_like(dirty_truth)
    false_dirty = np.zeros_like(dirty_truth)
    false_dirty[1:3, 1:3] = True

    report = evaluate_segmentation(
        [shifted_prediction, false_dirty],
        [dirty_truth, clean],
    )

    assert report.dirty_recall == 1.0
    assert report.false_clean_rate == 0.0
    assert report.clean_specificity == 0.0
    assert report.false_dirty_rate == 1.0
    assert report.mean_centroid_error_px == pytest.approx(2 ** 0.5)
    assert 0.0 < report.mean_centroid_error_norm < 1.0


def test_missed_component_has_maximum_normalized_centroid_error():
    truth = np.zeros((10, 10), dtype=bool)
    truth[2:4, 2:4] = True
    report = evaluate_segmentation([np.zeros_like(truth)], [truth])
    assert report.false_clean_rate == 1.0
    assert report.mean_centroid_error_norm == 1.0


def test_threshold_sweep_keeps_false_clean_visible():
    probability = np.zeros((4, 4), dtype=np.float32)
    probability[1:3, 1:3] = 0.6
    truth = np.zeros((4, 4), dtype=bool)
    truth[1:3, 1:3] = True
    reports = threshold_sweep([probability], [truth], [0.5, 0.7])
    assert reports[0]['false_clean_rate'] == 0.0
    assert reports[1]['false_clean_rate'] == 1.0


def test_threshold_sweep_applies_runtime_component_filter_per_component():
    probability = np.zeros((8, 8), dtype=np.float32)
    probability[1, 1] = 0.99
    clean_truth = np.zeros((8, 8), dtype=bool)
    report = threshold_sweep(
        [probability],
        [clean_truth],
        [0.5],
        minimum_component_area=2,
    )[0]
    assert report['false_dirty_rate'] == 0.0


def test_panel_metrics_separate_partial_and_small_recall():
    report = evaluate_panel_detection(
        [
            {
                'image_width': 100,
                'image_height': 100,
                'ground_truth': [
                    {'bbox': [0, 10, 20, 20]},
                    {'bbox': [70, 70, 10, 10]},
                ],
                'predictions': [
                    {'bbox': [0, 10, 20, 20], 'score': 0.9},
                    {'bbox': [70, 70, 10, 10], 'score': 0.8},
                ],
            }
        ]
    )
    assert report['precision_iou50'] == 1.0
    assert report['recall_iou50'] == 1.0
    assert report['partial_panel_recall'] == 1.0
    assert report['small_distant_panel_recall'] == 1.0


def test_segmentation_metric_rejects_count_mismatch():
    mask = np.zeros((2, 2), dtype=bool)
    with pytest.raises(ValueError, match='counts'):
        evaluate_segmentation([mask, mask], [mask])


def test_augmentation_is_repeatable_for_the_same_seed_and_keeps_mask_binary():
    image = np.full((40, 60, 3), 120, dtype=np.uint8)
    mask = np.zeros((40, 60), dtype=np.uint8)
    mask[10:20, 20:30] = 255
    config = {
        'brightness_probability': 1.0,
        'color_probability': 1.0,
        'perspective_probability': 1.0,
        'perspective_limit': 0.02,
        'scale_probability': 1.0,
        'scale_limit': 0.03,
    }
    first = augment_image_mask(image, mask, config, np.random.default_rng(7))
    second = augment_image_mask(image, mask, config, np.random.default_rng(7))
    assert np.array_equal(first[0], second[0])
    assert np.array_equal(first[1], second[1])
    assert set(np.unique(first[1])).issubset({0, 255})
