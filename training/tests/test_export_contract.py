import pytest

from da_daka_training.export_model import _verify_threshold_provenance


def test_panel_export_threshold_must_match_validation_report():
    report = {
        'selection_split': 'validation',
        'score_threshold': 0.35,
    }
    _verify_threshold_provenance('panel_detection', report, 0.35)
    with pytest.raises(ValueError, match='does not match'):
        _verify_threshold_provenance('panel_detection', report, 0.50)


def test_dirt_export_requires_explicit_validation_selection():
    report = {
        'selection_split': 'validation',
        'selection_status': 'UNSELECTED_REQUIRES_PROJECT_RISK_REVIEW',
        'selected_threshold': 0.40,
    }
    with pytest.raises(ValueError, match='SELECTED_FROM_VALIDATION'):
        _verify_threshold_provenance('dirt_segmentation', report, 0.40)
    report['selection_status'] = 'SELECTED_FROM_VALIDATION'
    _verify_threshold_provenance('dirt_segmentation', report, 0.40)


def test_threshold_report_must_be_validation_split():
    with pytest.raises(ValueError, match='selection_split=validation'):
        _verify_threshold_provenance(
            'panel_detection',
            {'selection_split': 'test', 'score_threshold': 0.35},
            0.35,
        )
