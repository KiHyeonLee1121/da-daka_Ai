from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from control.visual_servo import MovementType, VisualServoController


def make_servo() -> VisualServoController:
    return VisualServoController(
        {
            "align_threshold_px": 40,
            "max_vx": 0.15,
            "max_vy": 0.15,
            "max_vz": 0.15,
            "invert_x": False,
            "invert_y": False,
            "axis_map": {"horizontal": "vy", "vertical": "vx", "distance": "vz"},
        },
        {"target_distance_m": 1.0, "tolerance_m": 0.1},
    )


def test_center_target_holds_when_distance_ok() -> None:
    servo = make_servo()
    cmd = servo.compute(640, 480, (320, 240), 1.0)
    assert cmd.command_type == MovementType.HOLD
    assert cmd.aligned is True
    assert cmd.distance_ok is True


def test_target_right_moves_right() -> None:
    servo = make_servo()
    cmd = servo.compute(640, 480, (450, 240), 1.0)
    assert cmd.command_type == MovementType.MOVE_RIGHT
    assert cmd.vy > 0


def test_target_left_moves_left() -> None:
    servo = make_servo()
    cmd = servo.compute(640, 480, (180, 240), 1.0)
    assert cmd.command_type == MovementType.MOVE_LEFT
    assert cmd.vy < 0


def test_too_close_retreats_from_panel() -> None:
    servo = make_servo()
    cmd = servo.compute(640, 480, (320, 240), 0.75)
    assert cmd.command_type == MovementType.RETREAT_FROM_PANEL
    assert cmd.vz < 0


def test_too_far_approaches_panel() -> None:
    servo = make_servo()
    cmd = servo.compute(640, 480, (320, 240), 1.25)
    assert cmd.command_type == MovementType.APPROACH_PANEL
    assert cmd.vz > 0
