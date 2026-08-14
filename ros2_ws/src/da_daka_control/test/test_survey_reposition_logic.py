"""Tests for bounded survey XY reposition helpers."""

import math

from da_daka_control.survey_reposition_logic import (
    advance_horizontal_setpoint,
    PrearmHeadingLatch,
    StableHorizontalArrival,
    target_validation_failures,
    wrapped_yaw_error,
)
import pytest


def test_horizontal_setpoint_step_is_speed_limited():
    """The command trajectory must not exceed its horizontal speed limit."""
    result = advance_horizontal_setpoint(
        (0.0, 0.0),
        (3.0, 4.0),
        maximum_speed_mps=0.2,
        dt_s=0.5,
    )
    assert result == pytest.approx((0.06, 0.08))
    assert math.hypot(*result) == pytest.approx(0.1)


def test_horizontal_setpoint_stops_exactly_at_target():
    """A short final step must land exactly on the requested coordinate."""
    result = advance_horizontal_setpoint(
        (1.0, 2.0),
        (1.01, 2.01),
        maximum_speed_mps=0.2,
        dt_s=0.1,
    )
    assert result == (1.01, 2.01)


def test_target_displacement_limit():
    """Targets beyond the configured flight envelope must be rejected."""
    assert not target_validation_failures(
        current_xy=(10.0, -5.0),
        target_xy=(13.0, -5.0),
        maximum_displacement_m=4.0,
    )
    failures = target_validation_failures(
        current_xy=(10.0, -5.0),
        target_xy=(15.0, -5.0),
        maximum_displacement_m=4.0,
    )
    assert 'exceeds' in failures[0]


def test_arrival_requires_continuous_stability():
    """One unstable sample must reset the stable-arrival interval."""
    arrival = StableHorizontalArrival(0.2, 0.1, 2.0)
    assert not arrival.update(
        position_error_m=0.1, speed_mps=0.05, now_s=1.0
    )
    assert not arrival.update(
        position_error_m=0.3, speed_mps=0.05, now_s=2.0
    )
    assert not arrival.update(
        position_error_m=0.1, speed_mps=0.05, now_s=3.0
    )
    assert arrival.update(
        position_error_m=0.1, speed_mps=0.05, now_s=5.0
    )


def test_wrapped_yaw_error_crosses_pi_boundary() -> None:
    """Yaw alignment must use the short path across plus/minus pi."""
    error = wrapped_yaw_error(math.radians(-179), math.radians(179))
    assert math.degrees(error) == pytest.approx(2.0)


def test_prearm_heading_is_valid_for_exactly_one_arm_cycle() -> None:
    """A captured disarmed heading must activate on arm and clear on disarm."""
    latch = PrearmHeadingLatch()
    latch.update_armed(False)
    latch.capture(math.radians(25.0))
    assert not latch.valid_for_current_arm

    latch.update_armed(True)
    assert latch.valid_for_current_arm
    assert math.degrees(latch.heading_rad) == pytest.approx(25.0)

    latch.update_armed(False)
    assert not latch.valid_for_current_arm
    assert latch.heading_rad is None


def test_prearm_heading_cannot_be_captured_while_armed() -> None:
    """Capturing after Arm must fail instead of accepting a flight yaw."""
    latch = PrearmHeadingLatch()
    latch.update_armed(True)
    with pytest.raises(ValueError, match='disarmed'):
        latch.capture(0.0)


def test_node_started_armed_has_no_prearm_reference() -> None:
    """Starting the node after Arm must not invent a pre-arm heading."""
    latch = PrearmHeadingLatch()
    latch.update_armed(True)
    assert not latch.valid_for_current_arm
    assert latch.heading_rad is None
