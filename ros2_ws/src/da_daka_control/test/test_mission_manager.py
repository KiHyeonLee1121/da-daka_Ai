"""Unit tests for mission-manager timing helpers."""

from da_daka_control.mission_manager_node import (
    MissionManagerNode,
    MissionState,
    StableWindow,
    status_failures,
)


def test_all_required_states_exist():
    expected = {
        'IDLE',
        'PRECHECK',
        'ARMING',
        'TAKEOFF',
        'WAIT_HOVER',
        'CHECK_SENSOR',
        'PRESTREAM_SETPOINT',
        'ENABLE_DISTANCE_CONTROL',
        'ENTER_OFFBOARD',
        'DISTANCE_CONTROL',
        'TARGET_HOLD',
        'LOITER_HANDOVER',
        'AUTO_LAND',
        'WAIT_DISARM',
        'COMPLETE',
        'ABORT',
    }
    assert {state.name for state in MissionState} == expected


def test_stable_window_requires_continuous_duration():
    window = StableWindow(2.0)
    assert not window.update(True, 10.0)
    assert not window.update(True, 11.9)
    assert window.update(True, 12.0)


def test_stable_window_resets_on_false_condition():
    window = StableWindow(2.0)
    assert not window.update(True, 10.0)
    assert not window.update(False, 11.0)
    assert not window.update(True, 12.0)
    assert window.update(True, 14.0)


def test_optional_number_formats_csv_values():
    assert MissionManagerNode._optional_number(None) == ''
    assert MissionManagerNode._optional_number(1.25) == '1.250000'


def test_takeoff_and_control_states_require_armed_vehicle():
    assert MissionState.TAKEOFF in MissionManagerNode.ARMED_REQUIRED_STATES
    assert (
        MissionState.DISTANCE_CONTROL
        in MissionManagerNode.ARMED_REQUIRED_STATES
    )
    assert MissionState.AUTO_LAND not in MissionManagerNode.ARMED_REQUIRED_STATES
    assert (
        MissionState.WAIT_DISARM
        not in MissionManagerNode.ARMED_REQUIRED_STATES
    )


def test_external_mode_override_detected_during_distance_control():
    assert MissionManagerNode._is_external_mode_override(
        MissionState.DISTANCE_CONTROL,
        'OFFBOARD',
        'AUTO.LOITER',
        True,
    )


def test_expected_handover_is_not_external_override():
    assert not MissionManagerNode._is_external_mode_override(
        MissionState.LOITER_HANDOVER,
        'OFFBOARD',
        'AUTO.LOITER',
        True,
    )


def test_mode_change_before_offboard_is_not_external_override():
    assert not MissionManagerNode._is_external_mode_override(
        MissionState.ENTER_OFFBOARD,
        'AUTO.LOITER',
        'AUTO.LAND',
        False,
    )


def test_external_land_during_prestream_is_respected():
    assert MissionManagerNode._is_external_land_override(
        MissionState.PRESTREAM_SETPOINT,
        'AUTO.LOITER',
        'AUTO.LAND',
        True,
        'AUTO.LAND',
    )


def test_manager_requested_land_is_not_external_override():
    assert not MissionManagerNode._is_external_land_override(
        MissionState.AUTO_LAND,
        'AUTO.LOITER',
        'AUTO.LAND',
        True,
        'AUTO.LAND',
    )


def healthy_status(**overrides):
    """Return status-failure arguments representing a flight-ready vehicle."""
    values = {
        'now_s': 10.0,
        'timeout_s': 2.0,
        'battery_remaining': 0.8,
        'battery_time_s': 9.5,
        'minimum_battery_remaining': 0.3,
        'landed_state': 1,
        'extended_state_time_s': 9.5,
        'require_on_ground': True,
        'sensors_enabled': 0x3f,
        'sensors_health': 0x3f,
        'sys_status_time_s': 9.5,
        'require_enabled_sensors_healthy': True,
    }
    values.update(overrides)
    return values


def test_healthy_status_passes_preflight_gate():
    assert status_failures(**healthy_status()) == []


def test_low_battery_is_rejected():
    failures = status_failures(
        **healthy_status(battery_remaining=0.12)
    )
    assert any('battery 12% below 30%' in failure for failure in failures)


def test_stale_status_and_unhealthy_enabled_sensor_are_rejected():
    stale = status_failures(**healthy_status(sys_status_time_s=7.0))
    assert 'PX4 system status unavailable or stale' in stale

    unhealthy = status_failures(
        **healthy_status(sensors_health=0x1f)
    )
    assert any('mask=0x20' in failure for failure in unhealthy)


def test_vehicle_must_be_on_ground_only_during_preflight():
    preflight = status_failures(**healthy_status(landed_state=2))
    assert any('not confirmed on ground' in failure for failure in preflight)

    inflight = status_failures(
        **healthy_status(landed_state=2, require_on_ground=False)
    )
    assert inflight == []
