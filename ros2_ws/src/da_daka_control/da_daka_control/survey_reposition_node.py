"""Move only in Local ENU XY while preserving capture altitude and yaw."""

from enum import auto, Enum
import math
import time
from typing import Optional

from da_daka_control.survey_reposition_logic import (
    advance_horizontal_setpoint,
    StableHorizontalArrival,
    target_validation_failures,
    wrapped_yaw_error,
)
from geometry_msgs.msg import PoseStamped, TwistStamped
from mavros_msgs.msg import State
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import String
from std_srvs.srv import Trigger


class RepositionState(Enum):
    """Operator-gated states for one horizontal reposition."""

    IDLE = auto()
    PRESTREAM = auto()
    WAIT_OFFBOARD = auto()
    ALIGN_YAW = auto()
    MOVE = auto()
    TARGET_HOLD = auto()
    ABORT_HOLD = auto()
    HANDED_OVER = auto()
    ABORTED = auto()


class SurveyRepositionNode(Node):
    """Publish bounded XY position setpoints without flight-mode commands."""

    ACTIVE_STATES = {
        RepositionState.PRESTREAM,
        RepositionState.WAIT_OFFBOARD,
        RepositionState.ALIGN_YAW,
        RepositionState.MOVE,
        RepositionState.TARGET_HOLD,
        RepositionState.ABORT_HOLD,
    }

    def __init__(self) -> None:
        """Create subscriptions, guarded services, and the control timer."""
        super().__init__('survey_reposition')
        self._declare_parameters()
        self._load_parameters()

        latched_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._setpoint_pub = self.create_publisher(
            PoseStamped,
            '/mavros/setpoint_position/local',
            qos_profile_sensor_data,
        )
        self._state_pub = self.create_publisher(
            String, '/survey/reposition/state', latched_qos
        )
        self._result_pub = self.create_publisher(
            String, '/survey/reposition/result', latched_qos
        )
        self.create_service(Trigger, '/survey/reposition/start', self._start)
        self.create_service(Trigger, '/survey/reposition/abort', self._abort)
        self.create_subscription(
            State, '/mavros/state', self._mavros_state, 10
        )
        self.create_subscription(
            PoseStamped,
            '/mavros/local_position/pose',
            self._pose_callback,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            TwistStamped,
            '/mavros/local_position/velocity_local',
            self._velocity_callback,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            PoseStamped, self._target_topic, self._target_callback, 10
        )

        self._state = RepositionState.IDLE
        self._reason = 'IDLE'
        self._connected = False
        self._armed = False
        self._mode = ''
        self._pose: Optional[PoseStamped] = None
        self._pose_time_s: Optional[float] = None
        self._velocity_xy: Optional[tuple[float, float]] = None
        self._velocity_time_s: Optional[float] = None
        self._target_xy: Optional[tuple[float, float]] = None
        self._target_yaw_rad: Optional[float] = None
        self._target_time_s: Optional[float] = None
        self._current_yaw_rad: Optional[float] = None
        self._hold_z: Optional[float] = None
        self._command_xy: Optional[tuple[float, float]] = None
        self._command_yaw_rad: Optional[float] = None
        self._initial_mode = ''
        self._state_started_s = time.monotonic()
        self._last_tick_s = self._state_started_s
        self._yaw_aligned_since_s: Optional[float] = None
        self._arrival = StableHorizontalArrival(
            self._arrival_tolerance_m,
            self._arrival_max_speed_mps,
            self._arrival_stable_s,
        )
        self._publish_state()
        self._publish_result('IDLE')
        self.create_timer(1.0 / self._tick_rate_hz, self._tick)
        self.get_logger().info(
            'Survey reposition ready; it never arms or changes PX4 mode; '
            f'configuration_approved={self._configuration_approved}'
        )

    def _declare_parameters(self) -> None:
        self.declare_parameter('configuration_approved', False)
        self.declare_parameter('target_topic', '/survey/panel_target_local')
        self.declare_parameter('target_frame_id', 'map')
        self.declare_parameter('maximum_target_age_s', 30.0)
        self.declare_parameter('telemetry_timeout_s', 0.5)
        self.declare_parameter('maximum_horizontal_displacement_m', 4.0)
        self.declare_parameter('maximum_horizontal_speed_mps', 0.20)
        self.declare_parameter('maximum_vertical_drift_m', 0.40)
        self.declare_parameter('arrival_tolerance_m', 0.20)
        self.declare_parameter('arrival_max_speed_mps', 0.10)
        self.declare_parameter('arrival_stable_s', 2.0)
        self.declare_parameter('prestream_s', 2.0)
        self.declare_parameter('offboard_wait_timeout_s', 30.0)
        self.declare_parameter('yaw_alignment_tolerance_deg', 5.0)
        self.declare_parameter('yaw_alignment_stable_s', 0.5)
        self.declare_parameter('yaw_alignment_timeout_s', 10.0)
        self.declare_parameter('tick_rate_hz', 20.0)

    def _load_parameters(self) -> None:
        def value(name: str):
            return self.get_parameter(name).value

        self._configuration_approved = bool(value('configuration_approved'))
        self._target_topic = str(value('target_topic'))
        self._target_frame_id = str(value('target_frame_id'))
        self._maximum_target_age_s = float(value('maximum_target_age_s'))
        self._telemetry_timeout_s = float(value('telemetry_timeout_s'))
        self._maximum_displacement_m = float(
            value('maximum_horizontal_displacement_m')
        )
        self._maximum_speed_mps = float(
            value('maximum_horizontal_speed_mps')
        )
        self._maximum_vertical_drift_m = float(
            value('maximum_vertical_drift_m')
        )
        self._arrival_tolerance_m = float(value('arrival_tolerance_m'))
        self._arrival_max_speed_mps = float(value('arrival_max_speed_mps'))
        self._arrival_stable_s = float(value('arrival_stable_s'))
        self._prestream_s = float(value('prestream_s'))
        self._offboard_wait_timeout_s = float(
            value('offboard_wait_timeout_s')
        )
        self._yaw_alignment_tolerance_rad = math.radians(
            float(value('yaw_alignment_tolerance_deg'))
        )
        self._yaw_alignment_stable_s = float(
            value('yaw_alignment_stable_s')
        )
        self._yaw_alignment_timeout_s = float(
            value('yaw_alignment_timeout_s')
        )
        self._tick_rate_hz = float(value('tick_rate_hz'))
        positive = {
            'maximum_target_age_s': self._maximum_target_age_s,
            'telemetry_timeout_s': self._telemetry_timeout_s,
            'maximum_horizontal_displacement_m': self._maximum_displacement_m,
            'maximum_horizontal_speed_mps': self._maximum_speed_mps,
            'maximum_vertical_drift_m': self._maximum_vertical_drift_m,
            'arrival_tolerance_m': self._arrival_tolerance_m,
            'arrival_stable_s': self._arrival_stable_s,
            'prestream_s': self._prestream_s,
            'offboard_wait_timeout_s': self._offboard_wait_timeout_s,
            'yaw_alignment_tolerance_deg': (
                self._yaw_alignment_tolerance_rad
            ),
            'yaw_alignment_stable_s': self._yaw_alignment_stable_s,
            'yaw_alignment_timeout_s': self._yaw_alignment_timeout_s,
            'tick_rate_hz': self._tick_rate_hz,
        }
        invalid = [name for name, item in positive.items() if item <= 0.0]
        if invalid or self._arrival_max_speed_mps < 0.0:
            raise ValueError('invalid parameters: ' + ', '.join(invalid))
        if self._yaw_alignment_tolerance_rad >= math.pi:
            raise ValueError('yaw_alignment_tolerance_deg must be below 180')

    def _mavros_state(self, msg: State) -> None:
        self._connected = msg.connected
        self._armed = msg.armed
        self._mode = msg.mode

    def _pose_callback(self, msg: PoseStamped) -> None:
        yaw_rad = self._yaw_from_quaternion(msg.pose.orientation)
        if yaw_rad is None:
            self.get_logger().error('Ignoring pose with invalid quaternion')
            return
        self._pose = msg
        self._current_yaw_rad = yaw_rad
        self._pose_time_s = time.monotonic()

    def _velocity_callback(self, msg: TwistStamped) -> None:
        self._velocity_xy = (msg.twist.linear.x, msg.twist.linear.y)
        self._velocity_time_s = time.monotonic()

    def _target_callback(self, msg: PoseStamped) -> None:
        if self._state in self.ACTIVE_STATES:
            return
        if msg.header.frame_id != self._target_frame_id:
            self.get_logger().error(
                f'Ignoring target frame {msg.header.frame_id!r}; expected '
                f'{self._target_frame_id!r}'
            )
            return
        target = (msg.pose.position.x, msg.pose.position.y)
        target_yaw_rad = self._yaw_from_quaternion(msg.pose.orientation)
        if not all(math.isfinite(item) for item in target):
            self.get_logger().error('Ignoring non-finite survey target')
            return
        if target_yaw_rad is None:
            self.get_logger().error(
                'Ignoring survey target with invalid yaw quaternion'
            )
            return
        self._target_xy = target
        self._target_yaw_rad = target_yaw_rad
        self._target_time_s = time.monotonic()

    def _start(self, _request, response):
        now_s = time.monotonic()
        failures = self._start_failures(now_s)
        if failures:
            response.success = False
            response.message = '; '.join(failures)
            return response
        position = self._pose.pose.position
        self._hold_z = position.z
        self._command_xy = (position.x, position.y)
        self._command_yaw_rad = self._target_yaw_rad
        self._initial_mode = self._mode
        self._arrival.reset()
        self._yaw_aligned_since_s = None
        self._transition(
            RepositionState.PRESTREAM, 'setpoint prestream started'
        )
        response.success = True
        response.message = (
            'holding current Z/XY and commanding survey yaw; after '
            'prestream, operator may select OFFBOARD in QGC'
        )
        return response

    def _abort(self, _request, response):
        if self._state not in self.ACTIVE_STATES:
            response.success = False
            response.message = f'not active ({self._state.name})'
            return response
        if self._mode == 'OFFBOARD':
            if self._pose is not None:
                position = self._pose.pose.position
                self._command_xy = (position.x, position.y)
            if self._current_yaw_rad is not None:
                self._command_yaw_rad = self._current_yaw_rad
            self._transition(
                RepositionState.ABORT_HOLD,
                'abort requested; holding until operator exits OFFBOARD',
            )
        else:
            self._transition(RepositionState.ABORTED, 'abort requested')
        response.success = True
        response.message = self._reason
        return response

    def _start_failures(self, now_s: float) -> list[str]:
        failures = []
        if not self._configuration_approved:
            failures.append('configuration_approved is false')
        if self._state in self.ACTIVE_STATES:
            failures.append(f'already active in {self._state.name}')
        if not self._connected:
            failures.append('MAVROS is not connected')
        if not self._armed:
            failures.append('vehicle is not armed')
        if self._mode == 'OFFBOARD':
            failures.append('start before entering OFFBOARD')
        if not self._telemetry_fresh(now_s):
            failures.append('local pose or velocity is stale')
        if (
            self._target_xy is None
            or self._target_yaw_rad is None
            or self._target_time_s is None
        ):
            failures.append('survey target has not been received')
        elif now_s - self._target_time_s > self._maximum_target_age_s:
            failures.append('survey target is stale')
        if self._pose is not None and self._target_xy is not None:
            position = self._pose.pose.position
            failures.extend(target_validation_failures(
                current_xy=(position.x, position.y),
                target_xy=self._target_xy,
                maximum_displacement_m=self._maximum_displacement_m,
            ))
        position_publishers = len(self.get_publishers_info_by_topic(
            '/mavros/setpoint_position/local'
        ))
        velocity_publishers = len(self.get_publishers_info_by_topic(
            '/mavros/setpoint_velocity/cmd_vel'
        ))
        if position_publishers != 1:
            failures.append(
                'position setpoint publisher conflict '
                f'({position_publishers} publishers including this node)'
            )
        if velocity_publishers != 0:
            failures.append(
                f'velocity setpoint publisher conflict ({velocity_publishers})'
            )
        return failures

    def _telemetry_fresh(self, now_s: float) -> bool:
        return (
            self._pose_time_s is not None
            and self._velocity_time_s is not None
            and now_s - self._pose_time_s <= self._telemetry_timeout_s
            and now_s - self._velocity_time_s <= self._telemetry_timeout_s
        )

    def _tick(self) -> None:
        now_s = time.monotonic()
        dt_s = min(0.2, max(0.001, now_s - self._last_tick_s))
        self._last_tick_s = now_s
        if self._state not in self.ACTIVE_STATES:
            return

        if self._state == RepositionState.ABORT_HOLD:
            if self._mode != 'OFFBOARD':
                self._transition(
                    RepositionState.ABORTED,
                    f'operator handover confirmed in {self._mode}',
                )
                return
            self._publish_setpoint()
            return

        if self._state in {
            RepositionState.ALIGN_YAW,
            RepositionState.MOVE,
            RepositionState.TARGET_HOLD,
        }:
            if self._mode != 'OFFBOARD':
                self._transition(
                    RepositionState.HANDED_OVER,
                    f'external mode {self._mode} respected; setpoints stopped',
                )
                return
            if not self._telemetry_fresh(now_s):
                self._transition(
                    RepositionState.ABORT_HOLD,
                    'telemetry stale; holding last setpoint until '
                    'OFFBOARD exit',
                )
                self._publish_setpoint()
                return
            vertical_drift = abs(self._pose.pose.position.z - self._hold_z)
            if vertical_drift > self._maximum_vertical_drift_m:
                position = self._pose.pose.position
                self._command_xy = (position.x, position.y)
                self._command_yaw_rad = self._current_yaw_rad
                self._transition(
                    RepositionState.ABORT_HOLD,
                    f'vertical drift {vertical_drift:.2f} m exceeded limit',
                )
                self._publish_setpoint()
                return

        if self._state == RepositionState.PRESTREAM:
            if self._mode not in {self._initial_mode, 'OFFBOARD'}:
                self._transition(
                    RepositionState.ABORTED,
                    f'external mode {self._mode} selected during prestream',
                )
                return
            self._publish_setpoint()
            if now_s - self._state_started_s >= self._prestream_s:
                next_state = (
                    RepositionState.ALIGN_YAW
                    if self._mode == 'OFFBOARD'
                    else RepositionState.WAIT_OFFBOARD
                )
                reason = (
                    'OFFBOARD confirmed; aligning survey yaw'
                    if next_state == RepositionState.ALIGN_YAW
                    else 'waiting for operator to select OFFBOARD in QGC'
                )
                self._transition(next_state, reason)
            return

        if self._state == RepositionState.WAIT_OFFBOARD:
            if self._mode == 'OFFBOARD':
                self._yaw_aligned_since_s = None
                self._transition(
                    RepositionState.ALIGN_YAW,
                    'OFFBOARD confirmed; aligning survey yaw',
                )
                return
            if self._mode != self._initial_mode:
                self._transition(
                    RepositionState.ABORTED,
                    f'external mode {self._mode} selected; setpoints stopped',
                )
                return
            self._publish_setpoint()
            if now_s - self._state_started_s > self._offboard_wait_timeout_s:
                self._transition(
                    RepositionState.ABORTED,
                    'OFFBOARD was not selected before timeout',
                )
            return

        if self._state == RepositionState.ALIGN_YAW:
            self._publish_setpoint()
            yaw_error_rad = abs(wrapped_yaw_error(
                self._target_yaw_rad,
                self._current_yaw_rad,
            ))
            if yaw_error_rad > self._yaw_alignment_tolerance_rad:
                self._yaw_aligned_since_s = None
            elif self._yaw_aligned_since_s is None:
                self._yaw_aligned_since_s = now_s
            elif (
                now_s - self._yaw_aligned_since_s
                >= self._yaw_alignment_stable_s
            ):
                self._arrival.reset()
                self._transition(
                    RepositionState.MOVE,
                    f'survey yaw aligned; error '
                    f'{math.degrees(yaw_error_rad):.1f} deg',
                )
                return
            if now_s - self._state_started_s > self._yaw_alignment_timeout_s:
                self._command_yaw_rad = self._current_yaw_rad
                self._transition(
                    RepositionState.ABORT_HOLD,
                    f'yaw alignment timeout; error '
                    f'{math.degrees(yaw_error_rad):.1f} deg',
                )
            return

        if self._state == RepositionState.MOVE:
            self._command_xy = advance_horizontal_setpoint(
                self._command_xy,
                self._target_xy,
                maximum_speed_mps=self._maximum_speed_mps,
                dt_s=dt_s,
            )
            self._publish_setpoint()
            position = self._pose.pose.position
            error = math.hypot(
                self._target_xy[0] - position.x,
                self._target_xy[1] - position.y,
            )
            speed = math.hypot(*self._velocity_xy)
            if self._arrival.update(
                position_error_m=error,
                speed_mps=speed,
                now_s=now_s,
                telemetry_valid=self._telemetry_fresh(now_s),
            ):
                self._command_xy = self._target_xy
                self._transition(
                    RepositionState.TARGET_HOLD,
                    f'target stable; horizontal error {error:.2f} m',
                )
                self._publish_result(
                    f'TARGET_REACHED E={self._target_xy[0]:.3f} '
                    f'N={self._target_xy[1]:.3f} error={error:.3f}'
                )
            return

        if self._state == RepositionState.TARGET_HOLD:
            self._publish_setpoint()

    def _publish_setpoint(self) -> None:
        if (
            self._command_xy is None
            or self._hold_z is None
            or self._command_yaw_rad is None
        ):
            return
        msg = PoseStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self._target_frame_id
        msg.pose.position.x = self._command_xy[0]
        msg.pose.position.y = self._command_xy[1]
        msg.pose.position.z = self._hold_z
        half_yaw = 0.5 * self._command_yaw_rad
        msg.pose.orientation.z = math.sin(half_yaw)
        msg.pose.orientation.w = math.cos(half_yaw)
        self._setpoint_pub.publish(msg)

    @staticmethod
    def _yaw_from_quaternion(orientation) -> Optional[float]:
        """Normalize a quaternion and return its ENU yaw, if valid."""
        quaternion = (
            float(orientation.x),
            float(orientation.y),
            float(orientation.z),
            float(orientation.w),
        )
        if not all(math.isfinite(item) for item in quaternion):
            return None
        norm = math.sqrt(sum(item * item for item in quaternion))
        if norm <= 1e-6:
            return None
        x, y, z, w = (item / norm for item in quaternion)
        return math.atan2(
            2.0 * (w * z + x * y),
            1.0 - 2.0 * (y * y + z * z),
        )

    def _transition(self, state: RepositionState, reason: str) -> None:
        previous = self._state
        self._state = state
        self._reason = reason
        self._state_started_s = time.monotonic()
        self.get_logger().info(f'{previous.name} -> {state.name}: {reason}')
        self._publish_state()
        if state in {RepositionState.HANDED_OVER, RepositionState.ABORTED}:
            self._publish_result(f'{state.name}: {reason}')

    def _publish_state(self) -> None:
        self._state_pub.publish(
            String(data=f'{self._state.name}: {self._reason}')
        )

    def _publish_result(self, result: str) -> None:
        self._result_pub.publish(String(data=result))


def main(args=None) -> None:
    """Run the survey reposition node."""
    rclpy.init(args=args)
    node = SurveyRepositionNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
