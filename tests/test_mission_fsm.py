from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from control.mission_fsm import MissionFSM, MissionInputs, MissionState
from control.visual_servo import MovementCommand, MovementType
from sensors.lidar_reader import LiDARReading
from vision.dirt_detector_base import DirtDetectionResult
from vision.target_estimator import TargetEstimate


def make_fsm(max_retries: int = 3) -> MissionFSM:
    return MissionFSM(
        {
            "max_retries": max_retries,
            "stable_hold_time_s": 1.0,
            "search_timeout_s": 10.0,
            "verify_area_reduction_ratio": 0.5,
        },
        {"pulse_duration_s": 0.3, "stabilize_wait_s": 1.5},
    )


def make_inputs(
    *,
    found: bool = True,
    aligned: bool = False,
    distance_ok: bool = False,
    timestamp: float = 0.0,
    area: float = 500.0,
) -> MissionInputs:
    detection = (
        DirtDetectionResult(found=True, centroid=(320, 240), bbox=(300, 220, 40, 40), area=area, confidence=0.9)
        if found
        else DirtDetectionResult.empty()
    )
    target = (
        TargetEstimate(True, (320, 240), (300, 220, 40, 40), area, 0.9, 0.0, 0.0)
        if found
        else TargetEstimate(False, None, None, 0.0, 0.0, None, None)
    )
    command_type = MovementType.HOLD if aligned and distance_ok else MovementType.MOVE_RIGHT
    command = MovementCommand(
        command_type=command_type,
        vy=0.15 if not aligned else 0.0,
        aligned=aligned,
        distance_ok=distance_ok,
        error_x=0.0 if aligned else 120.0,
        error_y=0.0,
    )
    return MissionInputs(
        panel_found=True,
        detection=detection,
        target=target,
        lidar=LiDARReading(1.0 if distance_ok else 1.3, True, timestamp),
        visual_command=command,
        timestamp=timestamp,
    )


def test_no_dirt_from_detect_goes_done() -> None:
    fsm = make_fsm()
    fsm.state = MissionState.DETECT_DIRT
    out = fsm.update(make_inputs(found=False))
    assert out.state == MissionState.DONE
    assert out.done is True


def test_dirt_not_aligned_stays_align_target() -> None:
    fsm = make_fsm()
    fsm.state = MissionState.DETECT_DIRT
    out = fsm.update(make_inputs(found=True, aligned=False, distance_ok=False))
    assert out.state == MissionState.ALIGN_TARGET
    assert out.command.command_type == MovementType.MOVE_RIGHT


def test_aligned_and_distance_ok_progresses_to_spray() -> None:
    fsm = make_fsm()
    fsm.state = MissionState.ALIGN_TARGET

    out = fsm.update(make_inputs(found=True, aligned=True, distance_ok=True, timestamp=10.0))
    assert out.state == MissionState.STOP_BEFORE_SPRAY
    assert out.command.command_type == MovementType.STOP

    out = fsm.update(make_inputs(found=True, aligned=True, distance_ok=True, timestamp=11.1))
    assert out.state == MissionState.SPRAY
    assert out.should_spray is True


def test_retry_exceeded_aborts() -> None:
    fsm = make_fsm(max_retries=1)
    fsm.state = MissionState.RETRY
    fsm.retry_count = 1
    out = fsm.update(make_inputs(found=True, aligned=True, distance_ok=True))
    assert out.state == MissionState.ABORT
    assert out.abort is True
