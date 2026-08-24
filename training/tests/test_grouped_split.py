from da_daka_training.split import assert_no_group_leakage, grouped_split
import pytest


def test_grouped_split_keeps_sessions_together():
    samples = [
        {'sample_id': f'{group}-{index}', 'split_group': group}
        for group in ('session-a', 'session-b', 'session-c', 'session-d')
        for index in range(3)
    ]
    assignment = grouped_split(samples, seed='stable')
    assert_no_group_leakage(samples, assignment)
    for group in ('session-a', 'session-b', 'session-c', 'session-d'):
        assert len({assignment[f'{group}-{index}'] for index in range(3)}) == 1


def test_leakage_checker_rejects_same_session_in_two_splits():
    samples = [
        {'sample_id': 'a', 'split_group': 'same'},
        {'sample_id': 'b', 'split_group': 'same'},
    ]
    with pytest.raises(ValueError, match='leakage'):
        assert_no_group_leakage(samples, {'a': 'train', 'b': 'test'})
