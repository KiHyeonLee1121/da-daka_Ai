"""Tests for the complete autonomous cleaning mission state order."""

from da_daka_control.autonomous_cleaning_fsm import (
    AutonomousCleaningFsm,
    CleaningMissionState,
)
from da_daka_control.panel_mapping import PanelTarget


def panel(panel_id):
    return PanelTarget(panel_id, float(panel_id), 0.0, 1.0, 1.0, 0.9, 3)


def reach_first_panel(fsm):
    fsm.start()
    fsm.precheck_complete()
    fsm.armed()
    fsm.takeoff_complete()
    fsm.survey_complete([panel(2), panel(1)])
    fsm.route_planned([1, 2])
    assert fsm.state == CleaningMissionState.DESCEND
    fsm.descent_complete()
    fsm.panel_visible()
    assert fsm.state == CleaningMissionState.SLOW_APPROACH
    fsm.transit_arrived()
    fsm.panel_reacquired()


def test_clean_panel_is_skipped_without_spray():
    fsm = AutonomousCleaningFsm()
    reach_first_panel(fsm)
    fsm.cleanliness_result(False)
    assert fsm.state == CleaningMissionState.TRANSIT
    assert fsm.panels[0].clean
    assert fsm.panels[0].spray_attempts == 0
    assert fsm.current_panel.target.panel_id == 2


def test_dirty_panel_is_aligned_sprayed_verified_and_retried():
    fsm = AutonomousCleaningFsm(max_spray_attempts=3)
    reach_first_panel(fsm)
    fsm.cleanliness_result(True)
    assert fsm.state == CleaningMissionState.PRECISION_ALIGN
    fsm.alignment_complete()
    fsm.spray_complete()
    assert fsm.state == CleaningMissionState.VERIFY
    assert fsm.current_panel.spray_attempts == 1
    fsm.cleanliness_result(True)
    assert fsm.state == CleaningMissionState.PRECISION_ALIGN
    fsm.alignment_complete()
    fsm.spray_complete()
    fsm.cleanliness_result(False)
    assert fsm.state == CleaningMissionState.TRANSIT
    assert fsm.panels[0].spray_attempts == 2


def test_persistently_dirty_panel_aborts_after_bounded_attempts():
    fsm = AutonomousCleaningFsm(max_spray_attempts=1)
    reach_first_panel(fsm)
    fsm.cleanliness_result(True)
    fsm.alignment_complete()
    fsm.spray_complete()
    fsm.cleanliness_result(True)
    assert fsm.state == CleaningMissionState.ABORT
    assert 'remained dirty' in fsm.reason


def test_last_clean_panel_returns_home_and_lands():
    fsm = AutonomousCleaningFsm()
    fsm.start()
    fsm.precheck_complete()
    fsm.armed()
    fsm.takeoff_complete()
    fsm.survey_complete([panel(1)])
    fsm.route_planned([1])
    fsm.descent_complete()
    fsm.transit_arrived()
    fsm.panel_reacquired()
    fsm.cleanliness_result(False)
    assert fsm.state == CleaningMissionState.RETURN_HOME
    fsm.home_arrived()
    fsm.landed()
    assert fsm.state == CleaningMissionState.COMPLETE
