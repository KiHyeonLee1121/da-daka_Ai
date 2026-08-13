"""Pure state machine: patrol a route once, then re-walk it holding 1 m."""

from collections import deque
from enum import auto, Enum
import math
from typing import Deque, Optional

from da_daka_control.panel_mission_fsm import (  # noqa: F401 (re-exported)
    advance_position_setpoint,
    control_ownership_failures,
    PanelRoute,
    RelativeWaypoint,
    StableArrival,
)


def body_offset_to_enu(
    *,
    forward_m: float,
    left_m: float,
    launch_yaw_rad: float,
) -> tuple[float, float]:
    """Rotate a launch-body FLU offset into the fixed local ENU frame."""
    values = (forward_m, left_m, launch_yaw_rad)
    if not all(math.isfinite(item) for item in values):
        raise ValueError('body-to-ENU inputs must be finite')
    cosine = math.cos(launch_yaw_rad)
    sine = math.sin(launch_yaw_rad)
    return (
        cosine * forward_m - sine * left_m,
        sine * forward_m + cosine * left_m,
    )


def wrapped_yaw_error(target_rad: float, current_rad: float) -> float:
    """Return the shortest signed yaw error in radians."""
    if not math.isfinite(target_rad) or not math.isfinite(current_rad):
        raise ValueError('yaw angles must be finite')
    return (target_rad - current_rad + math.pi) % (2.0 * math.pi) - math.pi


class StableYawReference:
    """Estimate a circular-mean yaw after a stable, full-duration window."""

    def __init__(self, duration_s: float, maximum_deviation_rad: float) -> None:
        if duration_s <= 0.0:
            raise ValueError('duration_s must be positive')
        if not 0.0 < maximum_deviation_rad < math.pi:
            raise ValueError('maximum_deviation_rad must be in (0, pi)')
        self.duration_s = duration_s
        self.maximum_deviation_rad = maximum_deviation_rad
        self.reset()

    def reset(self) -> None:
        """Clear collected yaw samples and the stable result."""
        self._samples: Deque[tuple[float, float]] = deque()
        self.stable_yaw_rad: Optional[float] = None

    def update(self, yaw_rad: float, now_s: float) -> Optional[float]:
        """Return circular-mean yaw once the complete window is stable."""
        if not math.isfinite(yaw_rad) or not math.isfinite(now_s):
            raise ValueError('yaw and time must be finite')
        if self._samples and now_s <= self._samples[-1][0]:
            self.reset()
        if (
            self._samples
            and now_s - self._samples[-1][0] >= self.duration_s
        ):
            self.reset()
        self._samples.append((now_s, yaw_rad))
        while (
            len(self._samples) >= 2
            and now_s - self._samples[1][0] >= self.duration_s
        ):
            self._samples.popleft()
        coverage_s = now_s - self._samples[0][0]
        if coverage_s < self.duration_s:
            self.stable_yaw_rad = None
            return None
        mean_yaw_rad = math.atan2(
            sum(math.sin(yaw) for _, yaw in self._samples),
            sum(math.cos(yaw) for _, yaw in self._samples),
        )
        maximum_deviation = max(
            abs(wrapped_yaw_error(mean_yaw_rad, yaw))
            for _, yaw in self._samples
        )
        self.stable_yaw_rad = (
            mean_yaw_rad
            if maximum_deviation <= self.maximum_deviation_rad
            else None
        )
        return self.stable_yaw_rad


def lidar_referenced_local_z_target(
    *,
    local_z_m: float,
    measured_distance_m: float,
    target_distance_m: float,
    gain: float,
    maximum_offset_m: float,
    tolerance_m: float,
) -> float:
    """Convert a LiDAR height error into a bounded relative Local-Z target."""
    values = (
        local_z_m,
        measured_distance_m,
        target_distance_m,
        gain,
        maximum_offset_m,
        tolerance_m,
    )
    if not all(math.isfinite(item) for item in values):
        raise ValueError('LiDAR height target inputs must be finite')
    if target_distance_m <= 0.0:
        raise ValueError('target_distance_m must be positive')
    if gain <= 0.0 or maximum_offset_m <= 0.0 or tolerance_m <= 0.0:
        raise ValueError('gain, maximum_offset_m and tolerance_m must be positive')

    error_m = target_distance_m - measured_distance_m
    if abs(error_m) <= tolerance_m:
        return local_z_m
    correction_m = max(
        -maximum_offset_m,
        min(maximum_offset_m, gain * error_m),
    )
    return local_z_m + correction_m


class MissionPhase(Enum):
    """Which of the two route passes is currently running."""

    PATROL = auto()
    DISTANCE = auto()


class PanelDistanceMissionState(Enum):
    """States for the two-pass route + per-panel distance-hold mission."""

    IDLE = auto()
    PRECHECK = auto()
    ARMING = auto()
    TAKEOFF = auto()
    TAKEOFF_PRESTREAM = auto()
    TAKEOFF_OFFBOARD = auto()
    TAKEOFF_HOLD = auto()
    LOITER_HANDOVER = auto()
    MOVE_PRESTREAM = auto()
    MOVE_OFFBOARD = auto()
    MOVE_TO_PANEL = auto()
    ARRIVE_LOITER = auto()
    DISTANCE_PRESTREAM = auto()
    DISTANCE_OFFBOARD = auto()
    DISTANCE_CONTROL = auto()
    DISTANCE_HOLD = auto()
    DISTANCE_LOITER = auto()
    PANEL_PAUSE = auto()
    RETURN_HOME_PRESTREAM = auto()
    RETURN_HOME_OFFBOARD = auto()
    RETURN_HOME = auto()
    FINAL_LOITER = auto()
    AUTO_LAND = auto()
    WAIT_DISARM = auto()
    COMPLETE = auto()
    ABORT = auto()


class PanelDistanceMissionFsm:
    """Hold mission state without performing ROS or MAVLink I/O."""

    # Pass 1 (PATROL) walks the route forward (index 0 -> N-1), pausing
    # briefly at each waypoint without touching the distance controller.
    # Pass 2 (DISTANCE) walks the same route backward from wherever PATROL
    # ended (index N-1 -> 0), holding target_distance_m at each waypoint
    # before a longer pause. Landing happens at whichever waypoint DISTANCE
    # finishes on.

    ACTIVE_STATES = frozenset(
        state
        for state in PanelDistanceMissionState
        if state not in {
            PanelDistanceMissionState.IDLE,
            PanelDistanceMissionState.COMPLETE,
            PanelDistanceMissionState.ABORT,
        }
    )

    def __init__(self, route: PanelRoute) -> None:
        self.route = route
        self.state = PanelDistanceMissionState.IDLE
        self.phase = MissionPhase.PATROL
        self.reason = 'IDLE'

    @property
    def active(self) -> bool:
        """Return whether the mission owns an active flight sequence."""
        return self.state in self.ACTIVE_STATES

    def start(self) -> None:
        """Start a new mission from an inactive terminal state."""
        if self.active:
            raise RuntimeError(f'mission already active in {self.state.name}')
        self.route.reset()
        self.phase = MissionPhase.PATROL
        self.state = PanelDistanceMissionState.PRECHECK
        self.reason = 'mission requested'

    def transition(
        self,
        state: PanelDistanceMissionState,
        reason: str = '',
    ) -> None:
        """Move to a state and retain an operator-readable reason."""
        self.state = state
        self.reason = reason or state.name

    def panel_move_arrived(self) -> None:
        """Handle arrival at a waypoint: pause-only in PATROL, hold in DISTANCE."""
        if self.state != PanelDistanceMissionState.MOVE_TO_PANEL:
            raise RuntimeError('panel_move_arrived is only valid while moving')
        if self.phase is MissionPhase.PATROL:
            self.transition(PanelDistanceMissionState.PANEL_PAUSE)
        else:
            self.transition(PanelDistanceMissionState.ARRIVE_LOITER)

    def distance_hold_complete(self) -> None:
        """Enter the post-hold pause once the distance controller is off."""
        if self.state != PanelDistanceMissionState.DISTANCE_LOITER:
            raise RuntimeError('distance loiter is not active')
        self.transition(PanelDistanceMissionState.PANEL_PAUSE)

    def panel_pause_complete(self) -> None:
        """Advance the route (direction depends on phase) or finish up."""
        if self.state != PanelDistanceMissionState.PANEL_PAUSE:
            raise RuntimeError('panel pause is not active')
        if self.phase is MissionPhase.PATROL:
            if self.route.advance():
                # Position OFFBOARD remains active between forward panels.
                self.transition(PanelDistanceMissionState.MOVE_TO_PANEL)
            else:
                # Start the reverse distance pass at panel 4 immediately.
                self.phase = MissionPhase.DISTANCE
                self.transition(PanelDistanceMissionState.ARRIVE_LOITER)
        else:
            if self.route.retreat():
                # Move to the next reverse waypoint holding the current
                # distance-hold altitude instead of climbing back to cruise
                # height; distance_control was disabled and mode switched to
                # loiter_mode during DISTANCE_LOITER, so re-enter OFFBOARD
                # via the same prestream handshake used elsewhere.
                self.transition(PanelDistanceMissionState.MOVE_PRESTREAM)
            else:
                # The final reverse panel is 3 m forward of launch. Return to
                # the launch origin at the 1 m reverse-transit height before
                # handing over to AUTO.LAND.
                self.transition(
                    PanelDistanceMissionState.RETURN_HOME_PRESTREAM
                )

    def abort(self, reason: str) -> None:
        """Latch an aborted terminal state."""
        self.transition(PanelDistanceMissionState.ABORT, reason)
