"""Pure horizontal setpoint helpers for the survey reacquisition test."""

import math
from typing import Optional


class PrearmHeadingLatch:
    """Keep one operator-captured yaw valid for exactly one arm cycle."""

    def __init__(self) -> None:
        """Create an empty latch with no observed MAVROS arm state."""
        self.heading_rad: Optional[float] = None
        self.valid_for_current_arm = False
        self._state_received = False
        self._armed = False

    def capture(self, yaw_rad: float) -> None:
        """Store a finite heading while the observed vehicle is disarmed."""
        if not self._state_received:
            raise ValueError('MAVROS arm state has not been received')
        if self._armed:
            raise ValueError('pre-arm heading can only be captured disarmed')
        if not math.isfinite(yaw_rad):
            raise ValueError('pre-arm heading must be finite')
        self.heading_rad = wrapped_yaw_error(yaw_rad, 0.0)
        self.valid_for_current_arm = False

    def update_armed(self, armed: bool) -> None:
        """Activate on an arm edge and clear after the matching disarm."""
        armed = bool(armed)
        if not self._state_received:
            self._state_received = True
            self._armed = armed
            if armed:
                self.heading_rad = None
                self.valid_for_current_arm = False
            return
        if not self._armed and armed:
            self.valid_for_current_arm = self.heading_rad is not None
        elif self._armed and not armed:
            self.heading_rad = None
            self.valid_for_current_arm = False
        self._armed = armed


def wrapped_yaw_error(target_rad: float, current_rad: float) -> float:
    """Return the shortest signed yaw error in radians."""
    if not math.isfinite(target_rad) or not math.isfinite(current_rad):
        raise ValueError('yaw angles must be finite')
    return (target_rad - current_rad + math.pi) % (2.0 * math.pi) - math.pi


def advance_horizontal_setpoint(
    current_xy: tuple[float, float],
    target_xy: tuple[float, float],
    *,
    maximum_speed_mps: float,
    dt_s: float,
) -> tuple[float, float]:
    """Advance an ENU XY setpoint without exceeding the configured speed."""
    if maximum_speed_mps <= 0.0:
        raise ValueError('maximum_speed_mps must be positive')
    if dt_s <= 0.0:
        raise ValueError('dt_s must be positive')
    if not all(math.isfinite(value) for value in current_xy + target_xy):
        raise ValueError('setpoint coordinates must be finite')

    delta_x = target_xy[0] - current_xy[0]
    delta_y = target_xy[1] - current_xy[1]
    distance = math.hypot(delta_x, delta_y)
    maximum_step = maximum_speed_mps * dt_s
    if distance <= maximum_step:
        return target_xy
    scale = maximum_step / distance
    return (
        current_xy[0] + delta_x * scale,
        current_xy[1] + delta_y * scale,
    )


def target_validation_failures(
    *,
    current_xy: tuple[float, float],
    target_xy: tuple[float, float],
    maximum_displacement_m: float,
) -> list[str]:
    """Return reasons an absolute MAVROS Local ENU target is unsafe."""
    if maximum_displacement_m <= 0.0:
        raise ValueError('maximum_displacement_m must be positive')
    if not all(math.isfinite(value) for value in current_xy + target_xy):
        return ['current or target XY is not finite']
    displacement = math.hypot(
        target_xy[0] - current_xy[0],
        target_xy[1] - current_xy[1],
    )
    if displacement > maximum_displacement_m:
        return [
            f'target displacement {displacement:.2f} m exceeds '
            f'{maximum_displacement_m:.2f} m'
        ]
    return []


class StableHorizontalArrival:
    """Require horizontal position and speed to remain settled."""

    def __init__(
        self,
        position_tolerance_m: float,
        maximum_speed_mps: float,
        duration_s: float,
    ) -> None:
        """Configure the position, speed, and continuous-time limits."""
        if position_tolerance_m <= 0.0:
            raise ValueError('position_tolerance_m must be positive')
        if maximum_speed_mps < 0.0:
            raise ValueError('maximum_speed_mps cannot be negative')
        if duration_s <= 0.0:
            raise ValueError('duration_s must be positive')
        self.position_tolerance_m = position_tolerance_m
        self.maximum_speed_mps = maximum_speed_mps
        self.duration_s = duration_s
        self._stable_since_s: Optional[float] = None

    def reset(self) -> None:
        """Clear the continuous-arrival timer."""
        self._stable_since_s = None

    def update(
        self,
        *,
        position_error_m: float,
        speed_mps: float,
        now_s: float,
        telemetry_valid: bool = True,
    ) -> bool:
        """Return true after arrival conditions remain continuously true."""
        stable = (
            telemetry_valid
            and math.isfinite(position_error_m)
            and math.isfinite(speed_mps)
            and position_error_m <= self.position_tolerance_m
            and speed_mps <= self.maximum_speed_mps
        )
        if not stable:
            self.reset()
            return False
        if self._stable_since_s is None:
            self._stable_since_s = now_s
        return now_s - self._stable_since_s >= self.duration_s
