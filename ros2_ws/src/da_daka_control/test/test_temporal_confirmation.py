"""Tests for sequence-based clean/dirty confirmation."""

from da_daka_control.spray_sequence import PerceptionBarrier
from da_daka_control.temporal_confirmation import (
    TemporalCleanlinessConfirmation,
)
import pytest


def confirmer():
    return TemporalCleanlinessConfirmation(
        clean_consecutive_frames=3,
        dirty_consecutive_frames=1,
    )


def observe(value, sequence, *, tracker=None, barrier=None):
    tracker = tracker or confirmer()
    decision = tracker.observe(
        session_id='session-a',
        sequence=sequence,
        frame_id=sequence,
        dirt_found=value,
        barrier=barrier,
    )
    return tracker, decision


def test_clean_requires_three_distinct_consecutive_frames():
    tracker = confirmer()
    assert observe(False, 1, tracker=tracker)[1] is None
    assert observe(False, 2, tracker=tracker)[1] is None
    assert observe(False, 2, tracker=tracker)[1] is None
    assert observe(False, 3, tracker=tracker)[1] is False


def test_dirty_is_confirmed_quickly_and_resets_clean_streak():
    tracker = confirmer()
    observe(False, 1, tracker=tracker)
    assert observe(True, 2, tracker=tracker)[1] is True
    assert observe(False, 3, tracker=tracker)[1] is None


def test_flicker_never_confirms_clean():
    tracker = confirmer()
    for sequence, value in enumerate([False, True, False, True, False], 1):
        _tracker, decision = observe(value, sequence, tracker=tracker)
        assert decision is not False


def test_post_spray_barrier_rejects_old_frame():
    tracker = confirmer()
    barrier = PerceptionBarrier('session-a', 10, 10)
    assert observe(False, 10, tracker=tracker, barrier=barrier)[1] is None
    assert observe(False, 11, tracker=tracker, barrier=barrier)[1] is None
    assert observe(False, 12, tracker=tracker, barrier=barrier)[1] is None
    assert observe(False, 13, tracker=tracker, barrier=barrier)[1] is False


def test_out_of_order_freshness_is_rejected():
    tracker = confirmer()
    observe(False, 3, tracker=tracker)
    with pytest.raises(ValueError, match='stale'):
        observe(False, 2, tracker=tracker)
