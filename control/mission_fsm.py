from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Any

from control.visual_servo import MovementCommand
from sensors.lidar_reader import LiDARReading
from vision.dirt_detector_base import DirtDetectionResult
from vision.target_estimator import TargetEstimate


class MissionState(str, Enum):
    IDLE = "IDLE"
    SEARCH_PANEL = "SEARCH_PANEL"
    DETECT_DIRT = "DETECT_DIRT"
    ALIGN_TARGET = "ALIGN_TARGET"
    HOLD_DISTANCE = "HOLD_DISTANCE"
    STOP_BEFORE_SPRAY = "STOP_BEFORE_SPRAY"
    SPRAY = "SPRAY"
    WAIT_STABILIZE = "WAIT_STABILIZE"
    VERIFY_CLEAN = "VERIFY_CLEAN"
    DONE = "DONE"
    RETRY = "RETRY"
    ABORT = "ABORT"


@dataclass(slots=True)
class MissionInputs:
    panel_found: bool
    detection: DirtDetectionResult
    target: TargetEstimate
    lidar: LiDARReading
    visual_command: MovementCommand
    timestamp: float


@dataclass(slots=True)
class MissionOutput:
    state: MissionState
    command: MovementCommand
    should_spray: bool = False
    spray_duration_s: float = 0.0
    done: bool = False
    abort: bool = False
    retry_count: int = 0
    detection_streak: int = 0
    spray_count: int = 0
    message: str = ""


class MissionFSM:
    def __init__(self, mission_config: dict[str, Any], spray_config: dict[str, Any]):
        self.max_retries = int(mission_config.get("max_retries", 3))
        self.stable_hold_time_s = float(mission_config.get("stable_hold_time_s", 1.0))
        self.search_timeout_s = float(mission_config.get("search_timeout_s", 10.0))
        self.verify_area_reduction_ratio = float(mission_config.get("verify_area_reduction_ratio", 0.5))
        self.required_detection_frames = max(1, int(mission_config.get("required_detection_frames", 1)))
        self.target_stability_max_jump_px = float(mission_config.get("target_stability_max_jump_px", 0.0))
        self.min_spray_interval_s = float(mission_config.get("min_spray_interval_s", 0.0))
        self.max_spray_events = max(1, int(mission_config.get("max_spray_events", self.max_retries + 1)))
        self.spray_duration_s = float(spray_config.get("pulse_duration_s", 0.3))
        self.stabilize_wait_s = float(spray_config.get("stabilize_wait_s", 1.5))

        self.state = MissionState.IDLE
        self.retry_count = 0
        self.search_started_at: float | None = None
        self.stable_since: float | None = None
        self.last_spray_at: float | None = None
        self.wait_started_at: float | None = None
        self.reference_area: float | None = None
        self.detection_streak = 0
        self.last_centroid: tuple[int, int] | None = None
        self.spray_count = 0

    def start(self, now: float) -> None:
        self.state = MissionState.SEARCH_PANEL
        self.search_started_at = now

    def update(self, inputs: MissionInputs) -> MissionOutput:
        if self.state == MissionState.IDLE:
            return self._out(MovementCommand.no_target("idle"), "waiting for start")
        if self.state == MissionState.SEARCH_PANEL:
            return self._handle_search_panel(inputs)
        if self.state == MissionState.DETECT_DIRT:
            return self._handle_detect_dirt(inputs)
        if self.state == MissionState.ALIGN_TARGET:
            return self._handle_align_target(inputs)
        if self.state == MissionState.HOLD_DISTANCE:
            return self._handle_hold_distance(inputs)
        if self.state == MissionState.STOP_BEFORE_SPRAY:
            return self._handle_stop_before_spray(inputs)
        if self.state == MissionState.SPRAY:
            return self._handle_spray(inputs)
        if self.state == MissionState.WAIT_STABILIZE:
            return self._handle_wait_stabilize(inputs)
        if self.state == MissionState.VERIFY_CLEAN:
            return self._handle_verify_clean(inputs)
        if self.state == MissionState.RETRY:
            return self._handle_retry(inputs)
        if self.state == MissionState.ABORT:
            return self._out(MovementCommand.stop("abort"), "mission aborted", abort=True)
        if self.state == MissionState.DONE:
            return self._out(MovementCommand.hold("done"), "mission done", done=True)
        return self._out(MovementCommand.stop("unknown state"), "unknown state", abort=True)

    def _handle_search_panel(self, inputs: MissionInputs) -> MissionOutput:
        if inputs.panel_found:
            self.state = MissionState.DETECT_DIRT
            return self._handle_detect_dirt(inputs)

        if self.search_started_at is not None and inputs.timestamp - self.search_started_at > self.search_timeout_s:
            self.state = MissionState.ABORT
            return self._out(MovementCommand.stop("panel search timeout"), "panel search timeout", abort=True)
        return self._out(MovementCommand.no_target("searching panel"), "searching panel")

    def _handle_detect_dirt(self, inputs: MissionInputs) -> MissionOutput:
        if not inputs.detection.found:
            self.detection_streak = 0
            self.last_centroid = None
            self.state = MissionState.DONE
            return self._out(MovementCommand.hold("no dirt found"), "no dirt found", done=True)

        if not self._target_is_stable(inputs.detection.centroid):
            self.detection_streak = 1
            self.last_centroid = inputs.detection.centroid
            return self._out(MovementCommand.hold("confirming stable target"), "confirming stable target")

        self.detection_streak += 1
        self.last_centroid = inputs.detection.centroid
        if self.detection_streak < self.required_detection_frames:
            return self._out(MovementCommand.hold("confirming dirt detection"), "confirming dirt detection")

        if self.reference_area is None:
            self.reference_area = inputs.detection.area
        self.state = MissionState.ALIGN_TARGET
        return self._handle_align_target(inputs)

    def _handle_align_target(self, inputs: MissionInputs) -> MissionOutput:
        if not inputs.detection.found:
            self.detection_streak = 0
            self.last_centroid = None
            self.state = MissionState.DETECT_DIRT
            return self._out(MovementCommand.no_target("target lost"), "target lost")

        if not inputs.visual_command.aligned:
            self.stable_since = None
            return self._out(inputs.visual_command, "aligning target")

        self.state = MissionState.HOLD_DISTANCE
        return self._handle_hold_distance(inputs)

    def _handle_hold_distance(self, inputs: MissionInputs) -> MissionOutput:
        if not inputs.detection.found:
            self.detection_streak = 0
            self.last_centroid = None
            self.state = MissionState.DETECT_DIRT
            return self._out(MovementCommand.no_target("target lost during distance hold"), "target lost")

        if not inputs.visual_command.aligned:
            self.state = MissionState.ALIGN_TARGET
            self.stable_since = None
            return self._out(inputs.visual_command, "alignment drifted")

        if not inputs.visual_command.distance_ok:
            self.stable_since = None
            return self._out(inputs.visual_command, "adjusting distance")

        self.state = MissionState.STOP_BEFORE_SPRAY
        self.stable_since = inputs.timestamp
        return self._out(MovementCommand.stop("pre-spray stop"), "pre-spray stop")

    def _handle_stop_before_spray(self, inputs: MissionInputs) -> MissionOutput:
        if not inputs.detection.found:
            self.detection_streak = 0
            self.last_centroid = None
            self.state = MissionState.DETECT_DIRT
            self.stable_since = None
            return self._out(MovementCommand.no_target("target lost before spray"), "target lost")

        if not inputs.visual_command.aligned:
            self.state = MissionState.ALIGN_TARGET
            self.stable_since = None
            return self._out(inputs.visual_command, "alignment unstable")

        if not inputs.visual_command.distance_ok:
            self.state = MissionState.HOLD_DISTANCE
            self.stable_since = None
            return self._out(inputs.visual_command, "distance unstable")

        if self.stable_since is None:
            self.stable_since = inputs.timestamp

        stable_for = inputs.timestamp - self.stable_since
        if stable_for < self.stable_hold_time_s:
            return self._out(MovementCommand.stop("holding before spray"), "holding before spray")

        if self.spray_count >= self.max_spray_events:
            self.state = MissionState.ABORT
            return self._out(MovementCommand.stop("spray limit exceeded"), "spray limit exceeded", abort=True)

        if self.last_spray_at is not None:
            elapsed_since_spray = inputs.timestamp - self.last_spray_at
            if elapsed_since_spray < self.min_spray_interval_s:
                return self._out(MovementCommand.stop("spray cooldown"), "spray cooldown")

        self.state = MissionState.SPRAY
        self.last_spray_at = inputs.timestamp
        self.spray_count += 1
        return self._out(
            MovementCommand.stop("spray pulse"),
            "spray pulse",
            should_spray=True,
            spray_duration_s=self.spray_duration_s,
        )

    def _handle_spray(self, inputs: MissionInputs) -> MissionOutput:
        self.state = MissionState.WAIT_STABILIZE
        self.wait_started_at = self.last_spray_at or inputs.timestamp
        return self._out(MovementCommand.hold("waiting after spray"), "waiting after spray")

    def _handle_wait_stabilize(self, inputs: MissionInputs) -> MissionOutput:
        if self.wait_started_at is None:
            self.wait_started_at = inputs.timestamp
        if inputs.timestamp - self.wait_started_at >= self.stabilize_wait_s:
            self.state = MissionState.VERIFY_CLEAN
            return self._handle_verify_clean(inputs)
        return self._out(MovementCommand.hold("stabilizing"), "stabilizing")

    def _handle_verify_clean(self, inputs: MissionInputs) -> MissionOutput:
        if not inputs.detection.found:
            self.state = MissionState.DONE
            return self._out(MovementCommand.hold("verified clean"), "verified clean", done=True)

        if self.reference_area is not None:
            target_area = self.reference_area * self.verify_area_reduction_ratio
            if inputs.detection.area <= target_area:
                self.state = MissionState.DONE
                return self._out(MovementCommand.hold("area reduced enough"), "area reduced enough", done=True)

        self.state = MissionState.RETRY
        return self._out(MovementCommand.hold("dirt remains"), "dirt remains")

    def _handle_retry(self, inputs: MissionInputs) -> MissionOutput:
        if self.retry_count >= self.max_retries:
            self.state = MissionState.ABORT
            return self._out(MovementCommand.stop("retry limit exceeded"), "retry limit exceeded", abort=True)

        self.retry_count += 1
        self.stable_since = None
        self.wait_started_at = None
        self.state = MissionState.ALIGN_TARGET if inputs.detection.found else MissionState.DETECT_DIRT
        return self._out(inputs.visual_command, "retrying")

    def _target_is_stable(self, centroid: tuple[int, int] | None) -> bool:
        if centroid is None or self.last_centroid is None or self.target_stability_max_jump_px <= 0:
            return True
        dx = centroid[0] - self.last_centroid[0]
        dy = centroid[1] - self.last_centroid[1]
        return math.hypot(dx, dy) <= self.target_stability_max_jump_px

    def _out(
        self,
        command: MovementCommand,
        message: str,
        should_spray: bool = False,
        spray_duration_s: float = 0.0,
        done: bool = False,
        abort: bool = False,
    ) -> MissionOutput:
        return MissionOutput(
            state=self.state,
            command=command,
            should_spray=should_spray,
            spray_duration_s=spray_duration_s,
            done=done,
            abort=abort,
            retry_count=self.retry_count,
            detection_streak=self.detection_streak,
            spray_count=self.spray_count,
            message=message,
        )
