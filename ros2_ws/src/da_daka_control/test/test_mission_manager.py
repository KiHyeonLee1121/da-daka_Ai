"""Unit tests for mission-manager timing helpers."""

from da_daka_control.mission_manager_node import (
    MissionManagerNode,
    MissionState,
    StableWindow,
)


def test_all_required_states_exist():
    expected = {
        "IDLE",
        "PRECHECK",
        "ARMING",
        "TAKEOFF",
        "WAIT_HOVER",
        "CHECK_SENSOR",
        "PRESTREAM_SETPOINT",
        "ENABLE_DISTANCE_CONTROL",
        "ENTER_OFFBOARD",
        "DISTANCE_CONTROL",
        "TARGET_HOLD",
        "LOITER_HANDOVER",
        "AUTO_LAND",
        "WAIT_DISARM",
        "COMPLETE",
        "ABORT",
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
    assert MissionManagerNode._optional_number(None) == ""
    assert MissionManagerNode._optional_number(1.25) == "1.250000"


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
        "OFFBOARD",
        "AUTO.LOITER",
        True,
    )


def test_expected_handover_is_not_external_override():
    assert not MissionManagerNode._is_external_mode_override(
        MissionState.LOITER_HANDOVER,
        "OFFBOARD",
        "AUTO.LOITER",
        True,
    )


def test_mode_change_before_offboard_is_not_external_override():
    assert not MissionManagerNode._is_external_mode_override(
        MissionState.ENTER_OFFBOARD,
        "AUTO.LOITER",
        "AUTO.LAND",
        False,
    )


def test_external_land_during_prestream_is_respected():
    assert MissionManagerNode._is_external_land_override(
        MissionState.PRESTREAM_SETPOINT,
        "AUTO.LOITER",
        "AUTO.LAND",
        True,
        "AUTO.LAND",
    )


def test_manager_requested_land_is_not_external_override():
    assert not MissionManagerNode._is_external_land_override(
        MissionState.AUTO_LAND,
        "AUTO.LOITER",
        "AUTO.LAND",
        True,
        "AUTO.LAND",
    )
