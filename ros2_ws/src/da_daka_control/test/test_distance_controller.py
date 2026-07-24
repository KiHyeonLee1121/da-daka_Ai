"""Tests for distance PID sign, deadband and output limits."""

import math

from da_daka_control.distance_controller import (
    DistancePid,
    TargetStabilityDetector,
)


def make_controller() -> DistancePid:
    """Create a controller with deterministic P-only settings."""
    return DistancePid(
        target_distance_m=1.0,
        deadband_m=0.05,
        kp=0.6,
        ki=0.0,
        kd=0.0,
        integral_limit=0.3,
        max_speed_mps=0.25,
        slow_zone_m=0.30,
        max_accel_mps2=10.0,
    )


def test_above_target_commands_downward_velocity():
    speed, error = make_controller().update(1.5, 0.05)
    assert error < 0.0
    assert math.isclose(speed, -0.25)


def test_below_target_commands_upward_velocity():
    speed, error = make_controller().update(0.8, 0.05)
    assert error > 0.0
    assert speed > 0.0


def test_deadband_commands_stop():
    controller = make_controller()
    controller.update(1.5, 0.05)
    speed, _ = controller.update(1.03, 0.05)
    assert speed == 0.0


def make_stability_detector() -> TargetStabilityDetector:
    """Create a detector requiring five continuous stable seconds."""
    return TargetStabilityDetector(
        tolerance_m=0.05,
        duration_s=5.0,
        max_speed_mps=0.05,
    )


def test_target_requires_continuous_stable_duration():
    detector = make_stability_detector()
    assert not detector.update(0.02, 0.0, 10.0)
    assert not detector.update(0.01, 0.0, 14.9)
    assert detector.update(0.01, 0.0, 15.0)


def test_target_timer_resets_outside_tolerance():
    detector = make_stability_detector()
    assert not detector.update(0.01, 0.0, 10.0)
    assert not detector.update(0.06, 0.0, 12.0)
    assert not detector.update(0.01, 0.0, 14.0)
    assert detector.update(0.01, 0.0, 19.0)


def test_target_rejects_motion_and_invalid_flight_state():
    detector = make_stability_detector()
    assert not detector.update(0.01, 0.06, 10.0)
    assert not detector.update(0.01, 0.0, 14.0, flight_state_valid=False)
    assert not detector.update(0.01, 0.0, 18.0)
    assert detector.update(0.01, 0.0, 23.0)
