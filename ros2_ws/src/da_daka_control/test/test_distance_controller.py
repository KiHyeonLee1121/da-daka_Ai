"""Tests for distance PID sign, deadband and output limits."""

import math

from da_daka_control.distance_controller import (
    DistancePid,
    LocalTakeoffController,
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


def make_takeoff_controller() -> LocalTakeoffController:
    """Create a deterministic launch-relative Local Z controller."""
    return LocalTakeoffController(
        climb_height_m=1.1,
        tolerance_m=0.05,
        kp=0.8,
        max_speed_mps=0.5,
        slow_zone_m=0.4,
        max_accel_mps2=1.0,
    )


def test_local_takeoff_uses_launch_reference_not_global_zero():
    controller = make_takeoff_controller()
    assert math.isclose(controller.latch_launch_z(-32.4), -31.3)
    speed, error = controller.update(-32.4, 1.0)
    assert error > 0.0
    assert math.isclose(speed, 0.5)


def test_local_takeoff_duplicate_latch_keeps_original_target():
    controller = make_takeoff_controller()
    original_target = controller.latch_launch_z(10.0)

    duplicate_target = controller.latch_launch_z(10.7)

    assert math.isclose(original_target, 11.1)
    assert math.isclose(duplicate_target, original_target)
    assert math.isclose(controller.launch_z_m, 10.0)
    assert math.isclose(controller.target_z_m, 11.1)


def test_local_takeoff_respects_acceleration_and_speed_limits():
    controller = make_takeoff_controller()
    controller.latch_launch_z(4.0)
    first_speed, _ = controller.update(4.0, 0.1)
    second_speed, _ = controller.update(4.0, 0.1)
    assert math.isclose(first_speed, 0.1)
    assert math.isclose(second_speed, 0.2)
    for _ in range(10):
        speed, _ = controller.update(4.0, 0.1)
    assert math.isclose(speed, 0.5)


def test_local_takeoff_stops_inside_target_tolerance():
    controller = make_takeoff_controller()
    target_z = controller.latch_launch_z(10.0)
    controller.update(10.0, 1.0)
    speed, error = controller.update(target_z - 0.02, 0.1)
    assert abs(error) <= 0.05
    assert speed == 0.0


def test_local_takeoff_corrects_overshoot_downward():
    controller = make_takeoff_controller()
    target_z = controller.latch_launch_z(-5.0)
    speed, error = controller.update(target_z + 0.2, 1.0)
    assert error < 0.0
    assert speed < 0.0


def test_local_takeoff_rejects_missing_or_invalid_reference():
    controller = make_takeoff_controller()
    try:
        controller.update(0.0, 0.1)
    except RuntimeError:
        pass
    else:
        raise AssertionError('update before launch latch must fail')

    try:
        controller.latch_launch_z(math.nan)
    except ValueError:
        pass
    else:
        raise AssertionError('non-finite launch Z must fail')


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
