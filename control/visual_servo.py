from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class MovementType(str, Enum):
    MOVE_LEFT = "MOVE_LEFT"
    MOVE_RIGHT = "MOVE_RIGHT"
    MOVE_FORWARD = "MOVE_FORWARD"
    MOVE_BACKWARD = "MOVE_BACKWARD"
    APPROACH_PANEL = "APPROACH_PANEL"
    RETREAT_FROM_PANEL = "RETREAT_FROM_PANEL"
    HOLD = "HOLD"
    STOP = "STOP"
    NO_TARGET = "NO_TARGET"


@dataclass(slots=True)
class MovementCommand:
    command_type: MovementType
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0
    yaw_rate: float = 0.0
    error_x: float | None = None
    error_y: float | None = None
    aligned: bool = False
    distance_ok: bool = False
    reason: str = ""

    @classmethod
    def hold(cls, reason: str = "hold") -> "MovementCommand":
        return cls(command_type=MovementType.HOLD, aligned=True, distance_ok=True, reason=reason)

    @classmethod
    def stop(cls, reason: str = "stop") -> "MovementCommand":
        return cls(command_type=MovementType.STOP, aligned=True, distance_ok=True, reason=reason)

    @classmethod
    def no_target(cls, reason: str = "no target") -> "MovementCommand":
        return cls(command_type=MovementType.NO_TARGET, reason=reason)


class VisualServoController:
    """Screen-center visual servoing command generator.

    Axis signs and body-frame mappings depend on the camera/nozzle mounting and
    Pixhawk frame convention. Calibrate `invert_*` and `axis_map` on the real
    aircraft before enabling live MAVLink output.
    """

    def __init__(self, visual_config: dict[str, Any], lidar_config: dict[str, Any]):
        self.align_threshold_px = float(visual_config.get("align_threshold_px", 40))
        self.max_vx = float(visual_config.get("max_vx", 0.15))
        self.max_vy = float(visual_config.get("max_vy", 0.15))
        self.max_vz = float(visual_config.get("max_vz", 0.15))
        self.invert_x = bool(visual_config.get("invert_x", False))
        self.invert_y = bool(visual_config.get("invert_y", False))
        self.invert_z = bool(visual_config.get("invert_z", False))
        self.axis_map = visual_config.get(
            "axis_map",
            {"horizontal": "vy", "vertical": "vx", "distance": "vz"},
        )
        self.target_distance_m = float(lidar_config.get("target_distance_m", 1.0))
        self.tolerance_m = float(lidar_config.get("tolerance_m", 0.1))

    def compute(
        self,
        frame_width: int,
        frame_height: int,
        target_centroid: tuple[int, int] | None,
        lidar_distance_m: float | None,
    ) -> MovementCommand:
        if target_centroid is None:
            return MovementCommand.no_target()

        cx, cy = target_centroid
        error_x = float(cx - frame_width / 2.0)
        error_y = float(cy - frame_height / 2.0)
        aligned = abs(error_x) < self.align_threshold_px and abs(error_y) < self.align_threshold_px

        if not aligned:
            return self._alignment_command(error_x, error_y)

        if lidar_distance_m is None:
            return MovementCommand(
                command_type=MovementType.HOLD,
                error_x=error_x,
                error_y=error_y,
                aligned=True,
                distance_ok=False,
                reason="aligned but lidar invalid",
            )

        if lidar_distance_m < self.target_distance_m - self.tolerance_m:
            cmd = MovementCommand(
                command_type=MovementType.RETREAT_FROM_PANEL,
                error_x=error_x,
                error_y=error_y,
                aligned=True,
                distance_ok=False,
                reason="too close to panel",
            )
            self._set_axis(cmd, "distance", -self._sign_z() * self.max_vz)
            return cmd

        if lidar_distance_m > self.target_distance_m + self.tolerance_m:
            cmd = MovementCommand(
                command_type=MovementType.APPROACH_PANEL,
                error_x=error_x,
                error_y=error_y,
                aligned=True,
                distance_ok=False,
                reason="too far from panel",
            )
            self._set_axis(cmd, "distance", self._sign_z() * self.max_vz)
            return cmd

        return MovementCommand(
            command_type=MovementType.HOLD,
            error_x=error_x,
            error_y=error_y,
            aligned=True,
            distance_ok=True,
            reason="aligned and distance ok",
        )

    def _alignment_command(self, error_x: float, error_y: float) -> MovementCommand:
        command_type = MovementType.MOVE_RIGHT if error_x > 0 else MovementType.MOVE_LEFT
        if abs(error_y) > abs(error_x):
            command_type = MovementType.MOVE_BACKWARD if error_y > 0 else MovementType.MOVE_FORWARD

        cmd = MovementCommand(
            command_type=command_type,
            error_x=error_x,
            error_y=error_y,
            aligned=False,
            distance_ok=False,
            reason="visual alignment",
        )

        if abs(error_x) >= self.align_threshold_px:
            x_sign = 1.0 if error_x > 0 else -1.0
            if self.invert_x:
                x_sign *= -1.0
            self._set_axis(cmd, "horizontal", x_sign * self.max_vy)

        if abs(error_y) >= self.align_threshold_px:
            # Target above center means move forward by default; target below means backward.
            y_sign = -1.0 if error_y > 0 else 1.0
            if self.invert_y:
                y_sign *= -1.0
            self._set_axis(cmd, "vertical", y_sign * self.max_vx)

        return cmd

    def _set_axis(self, cmd: MovementCommand, axis_key: str, value: float) -> None:
        axis = str(self.axis_map.get(axis_key, "")).lower()
        if axis == "vx":
            cmd.vx = value
        elif axis == "vy":
            cmd.vy = value
        elif axis == "vz":
            cmd.vz = value

    def _sign_z(self) -> float:
        return -1.0 if self.invert_z else 1.0
