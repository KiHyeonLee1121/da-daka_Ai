"""Generate a limited vertical MAVROS velocity from filtered distance."""

from enum import Enum
import math
import time
from typing import Optional

from geometry_msgs.msg import PoseStamped, TwistStamped
from mavros_msgs.msg import State
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Range
from std_msgs.msg import Bool, Float32, String
from std_srvs.srv import SetBool


def clamp(value: float, lower: float, upper: float) -> float:
    """Clamp value to the inclusive lower and upper limits."""
    return min(max(value, lower), upper)


class VerticalControlMode(str, Enum):
    """Mutually exclusive command modes for the single velocity publisher."""

    DISABLED = 'DISABLED'
    LOCAL_TAKEOFF = 'LOCAL_TAKEOFF'
    LIDAR_DISTANCE = 'LIDAR_DISTANCE'


class LocalTakeoffController:
    """Generate limited ENU vertical speed from launch-relative local Z."""

    def __init__(
        self,
        climb_height_m: float,
        tolerance_m: float,
        kp: float,
        max_speed_mps: float,
        slow_zone_m: float,
        max_accel_mps2: float,
    ) -> None:
        if climb_height_m <= 0.0:
            raise ValueError('climb_height_m must be greater than zero')
        if tolerance_m <= 0.0:
            raise ValueError('tolerance_m must be greater than zero')
        if kp <= 0.0:
            raise ValueError('kp must be greater than zero')
        if max_speed_mps <= 0.0:
            raise ValueError('max_speed_mps must be greater than zero')
        if slow_zone_m <= 0.0:
            raise ValueError('slow_zone_m must be greater than zero')
        if max_accel_mps2 <= 0.0:
            raise ValueError('max_accel_mps2 must be greater than zero')
        self.climb_height_m = climb_height_m
        self.tolerance_m = tolerance_m
        self.kp = kp
        self.max_speed_mps = max_speed_mps
        self.slow_zone_m = slow_zone_m
        self.max_accel_mps2 = max_accel_mps2
        self.reset()

    def reset(self) -> None:
        """Clear the launch reference and rate-limiter state."""
        self.launch_z_m: Optional[float] = None
        self.target_z_m: Optional[float] = None
        self.previous_output = 0.0

    def latch_launch_z(self, local_z_m: float) -> float:
        """Latch a finite launch Z and return the relative climb target."""
        if not math.isfinite(local_z_m):
            raise ValueError('local_z_m must be finite')
        self.launch_z_m = float(local_z_m)
        self.target_z_m = self.launch_z_m + self.climb_height_m
        self.previous_output = 0.0
        return self.target_z_m

    def update(self, local_z_m: float, dt: float) -> tuple[float, float]:
        """Return limited ENU vertical speed and target-local Z error."""
        if self.target_z_m is None:
            raise RuntimeError('launch Z must be latched before update')
        if not math.isfinite(local_z_m):
            raise ValueError('local_z_m must be finite')
        if dt <= 0.0:
            raise ValueError('dt must be greater than zero')

        error = self.target_z_m - float(local_z_m)
        if abs(error) <= self.tolerance_m:
            self.previous_output = 0.0
            return 0.0, error

        speed_limit = self.max_speed_mps * min(
            1.0,
            abs(error) / self.slow_zone_m,
        )
        desired_output = clamp(
            self.kp * error,
            -speed_limit,
            speed_limit,
        )
        maximum_change = self.max_accel_mps2 * dt
        output = clamp(
            desired_output,
            self.previous_output - maximum_change,
            self.previous_output + maximum_change,
        )
        self.previous_output = output
        return output, error


class DistancePid:
    """Outer-loop PID with deadband, speed, acceleration and integral limits."""

    def __init__(
        self,
        target_distance_m: float,
        deadband_m: float,
        kp: float,
        ki: float,
        kd: float,
        integral_limit: float,
        max_speed_mps: float,
        slow_zone_m: float,
        max_accel_mps2: float,
    ) -> None:
        self.target_distance_m = target_distance_m
        self.deadband_m = deadband_m
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.integral_limit = integral_limit
        self.max_speed_mps = max_speed_mps
        self.slow_zone_m = slow_zone_m
        self.max_accel_mps2 = max_accel_mps2
        if target_distance_m <= 0.0:
            raise ValueError('target_distance_m must be greater than zero')
        if deadband_m < 0.0:
            raise ValueError('deadband_m cannot be negative')
        if integral_limit < 0.0:
            raise ValueError('integral_limit cannot be negative')
        if max_speed_mps <= 0.0:
            raise ValueError('max_speed_mps must be greater than zero')
        if slow_zone_m <= 0.0:
            raise ValueError('slow_zone_m must be greater than zero')
        if max_accel_mps2 <= 0.0:
            raise ValueError('max_accel_mps2 must be greater than zero')
        self.reset()

    def reset(self) -> None:
        """Clear accumulated PID and rate-limiter state."""
        self.integral = 0.0
        self.previous_error: Optional[float] = None
        self.previous_output = 0.0

    def update(self, measured_distance_m: float, dt: float) -> tuple[float, float]:
        """
        Return vertical ENU velocity and distance error.

        Positive Z moves upward. A measured distance larger than the target
        therefore creates a negative command, which moves the vehicle down.
        """
        if dt <= 0.0:
            raise ValueError('dt must be greater than zero')

        error = self.target_distance_m - measured_distance_m
        if abs(error) <= self.deadband_m:
            self.integral = 0.0
            self.previous_error = error
            self.previous_output = 0.0
            return 0.0, error
        else:
            self.integral = clamp(
                self.integral + error * dt,
                -self.integral_limit,
                self.integral_limit,
            )
            derivative = 0.0
            if self.previous_error is not None:
                derivative = (error - self.previous_error) / dt
            self.previous_error = error
            desired_output = (
                self.kp * error + self.ki * self.integral + self.kd * derivative
            )

            speed_scale = min(1.0, abs(error) / self.slow_zone_m)
            speed_limit = self.max_speed_mps * speed_scale
            desired_output = clamp(desired_output, -speed_limit, speed_limit)

        maximum_change = self.max_accel_mps2 * dt
        output = clamp(
            desired_output,
            self.previous_output - maximum_change,
            self.previous_output + maximum_change,
        )
        self.previous_output = output
        return output, error


class TargetStabilityDetector:
    """Detect continuous target hold without accepting a brief crossing."""

    def __init__(
        self,
        tolerance_m: float,
        duration_s: float,
        max_speed_mps: float,
    ) -> None:
        if tolerance_m <= 0.0:
            raise ValueError('tolerance_m must be greater than zero')
        if duration_s <= 0.0:
            raise ValueError('duration_s must be greater than zero')
        if max_speed_mps < 0.0:
            raise ValueError('max_speed_mps cannot be negative')
        self.tolerance_m = tolerance_m
        self.duration_s = duration_s
        self.max_speed_mps = max_speed_mps
        self.reset()

    def reset(self) -> None:
        """Clear the continuous in-band timer."""
        self._stable_since: Optional[float] = None
        self.reached = False

    def update(
        self,
        error_m: float,
        speed_mps: float,
        now_s: float,
        flight_state_valid: bool = True,
    ) -> bool:
        """Return true after error and speed remain stable for the duration."""
        stable = (
            flight_state_valid
            and abs(error_m) <= self.tolerance_m
            and abs(speed_mps) <= self.max_speed_mps
        )
        if not stable:
            self.reset()
            return False
        if self._stable_since is None:
            self._stable_since = now_s
        self.reached = now_s - self._stable_since >= self.duration_s
        return self.reached


class DistanceControllerNode(Node):
    """Own the single vertical-velocity publisher for mutually exclusive modes."""

    def __init__(self) -> None:
        super().__init__('distance_controller')
        self.declare_parameter('input_topic', '/distance/filtered')
        self.declare_parameter('command_topic', '/mavros/setpoint_velocity/cmd_vel')
        self.declare_parameter('enable_service', '/distance_control/enable')
        self.declare_parameter('enabled_state_topic', '/distance_control/enabled')
        self.declare_parameter(
            'target_reached_topic',
            '/distance_control/target_reached',
        )
        self.declare_parameter('frame_id', 'map')
        self.declare_parameter('control_rate_hz', 20.0)
        self.declare_parameter('enabled_on_startup', False)
        self.declare_parameter('require_mavros_connected', True)
        self.declare_parameter('sensor_timeout_s', 0.3)
        self.declare_parameter(
            'local_position_topic',
            '/mavros/local_position/pose',
        )
        self.declare_parameter(
            'local_velocity_topic',
            '/mavros/local_position/velocity_local',
        )
        self.declare_parameter('local_position_timeout_s', 0.3)
        self.declare_parameter(
            'local_takeoff_enable_service',
            '/local_takeoff/enable',
        )
        self.declare_parameter(
            'local_takeoff_enabled_state_topic',
            '/local_takeoff/enabled',
        )
        self.declare_parameter(
            'local_takeoff_target_reached_topic',
            '/local_takeoff/target_reached',
        )
        self.declare_parameter('control_mode_topic', '/vertical_control/mode')
        self.declare_parameter('local_takeoff_climb_height_m', 1.1)
        self.declare_parameter('local_takeoff_tolerance_m', 0.08)
        self.declare_parameter('local_takeoff_kp', 0.8)
        self.declare_parameter('local_takeoff_max_speed_mps', 0.4)
        self.declare_parameter('local_takeoff_slow_zone_m', 0.4)
        self.declare_parameter('local_takeoff_max_accel_mps2', 0.5)
        self.declare_parameter('local_takeoff_stable_duration_s', 2.0)
        self.declare_parameter('local_takeoff_stable_max_speed_mps', 0.08)
        self.declare_parameter('target_distance_m', 1.0)
        self.declare_parameter('deadband_m', 0.05)
        self.declare_parameter('kp', 0.6)
        self.declare_parameter('ki', 0.0)
        self.declare_parameter('kd', 0.0)
        self.declare_parameter('integral_limit', 0.3)
        self.declare_parameter('max_vertical_speed_mps', 0.25)
        self.declare_parameter('slow_zone_m', 0.30)
        self.declare_parameter('max_vertical_accel_mps2', 0.5)
        self.declare_parameter('target_stable_tolerance_m', 0.08)
        self.declare_parameter('target_stable_duration_s', 5.0)
        self.declare_parameter('target_stable_max_speed_mps', 0.05)

        self._input_topic = str(self.get_parameter('input_topic').value)
        command_topic = str(self.get_parameter('command_topic').value)
        enable_service = str(self.get_parameter('enable_service').value)
        enabled_state_topic = str(self.get_parameter('enabled_state_topic').value)
        target_reached_topic = str(
            self.get_parameter('target_reached_topic').value
        )
        local_position_topic = str(
            self.get_parameter('local_position_topic').value
        )
        local_velocity_topic = str(
            self.get_parameter('local_velocity_topic').value
        )
        local_takeoff_enable_service = str(
            self.get_parameter('local_takeoff_enable_service').value
        )
        local_takeoff_enabled_topic = str(
            self.get_parameter('local_takeoff_enabled_state_topic').value
        )
        local_takeoff_reached_topic = str(
            self.get_parameter('local_takeoff_target_reached_topic').value
        )
        control_mode_topic = str(
            self.get_parameter('control_mode_topic').value
        )
        self._frame_id = str(self.get_parameter('frame_id').value)
        self._control_rate_hz = float(self.get_parameter('control_rate_hz').value)
        self._enabled = bool(self.get_parameter('enabled_on_startup').value)
        self._require_mavros = bool(
            self.get_parameter('require_mavros_connected').value
        )
        self._sensor_timeout_s = float(self.get_parameter('sensor_timeout_s').value)
        self._local_position_timeout_s = float(
            self.get_parameter('local_position_timeout_s').value
        )

        if self._control_rate_hz <= 0.0:
            raise ValueError('control_rate_hz must be greater than zero')
        if self._sensor_timeout_s <= 0.0:
            raise ValueError('sensor_timeout_s must be greater than zero')
        if self._local_position_timeout_s <= 0.0:
            raise ValueError('local_position_timeout_s must be greater than zero')

        self._pid = DistancePid(
            target_distance_m=float(self.get_parameter('target_distance_m').value),
            deadband_m=float(self.get_parameter('deadband_m').value),
            kp=float(self.get_parameter('kp').value),
            ki=float(self.get_parameter('ki').value),
            kd=float(self.get_parameter('kd').value),
            integral_limit=float(self.get_parameter('integral_limit').value),
            max_speed_mps=float(
                self.get_parameter('max_vertical_speed_mps').value
            ),
            slow_zone_m=float(self.get_parameter('slow_zone_m').value),
            max_accel_mps2=float(
                self.get_parameter('max_vertical_accel_mps2').value
            ),
        )
        self._stability_detector = TargetStabilityDetector(
            tolerance_m=float(
                self.get_parameter('target_stable_tolerance_m').value
            ),
            duration_s=float(
                self.get_parameter('target_stable_duration_s').value
            ),
            max_speed_mps=float(
                self.get_parameter('target_stable_max_speed_mps').value
            ),
        )
        self._local_takeoff_controller = LocalTakeoffController(
            climb_height_m=float(
                self.get_parameter('local_takeoff_climb_height_m').value
            ),
            tolerance_m=float(
                self.get_parameter('local_takeoff_tolerance_m').value
            ),
            kp=float(self.get_parameter('local_takeoff_kp').value),
            max_speed_mps=float(
                self.get_parameter('local_takeoff_max_speed_mps').value
            ),
            slow_zone_m=float(
                self.get_parameter('local_takeoff_slow_zone_m').value
            ),
            max_accel_mps2=float(
                self.get_parameter('local_takeoff_max_accel_mps2').value
            ),
        )
        self._local_takeoff_stability = TargetStabilityDetector(
            tolerance_m=float(
                self.get_parameter('local_takeoff_tolerance_m').value
            ),
            duration_s=float(
                self.get_parameter('local_takeoff_stable_duration_s').value
            ),
            max_speed_mps=float(
                self.get_parameter('local_takeoff_stable_max_speed_mps').value
            ),
        )
        self._mode = (
            VerticalControlMode.LIDAR_DISTANCE
            if self._enabled
            else VerticalControlMode.DISABLED
        )
        self._latest_distance_m: Optional[float] = None
        self._last_sensor_time: Optional[float] = None
        self._local_z_m: Optional[float] = None
        self._local_z_time: Optional[float] = None
        self._local_vertical_speed_mps: Optional[float] = None
        self._local_velocity_time: Optional[float] = None
        self._last_control_time = time.monotonic()
        self._mavros_connected = False
        self._mavros_armed = False
        self._mavros_mode = ''
        self._watchdog_active = False
        self._target_reached = False
        self._local_takeoff_reached = False

        self._command_publisher = self.create_publisher(
            TwistStamped,
            command_topic,
            qos_profile_sensor_data,
        )
        self._error_publisher = self.create_publisher(
            Float32,
            '/distance_control/error',
            10,
        )
        self._speed_publisher = self.create_publisher(
            Float32,
            '/distance_control/vertical_speed_cmd',
            10,
        )
        state_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._enabled_publisher = self.create_publisher(
            Bool,
            enabled_state_topic,
            state_qos,
        )
        self._target_reached_publisher = self.create_publisher(
            Bool,
            target_reached_topic,
            state_qos,
        )
        self._local_takeoff_enabled_publisher = self.create_publisher(
            Bool,
            local_takeoff_enabled_topic,
            state_qos,
        )
        self._local_takeoff_reached_publisher = self.create_publisher(
            Bool,
            local_takeoff_reached_topic,
            state_qos,
        )
        self._control_mode_publisher = self.create_publisher(
            String,
            control_mode_topic,
            state_qos,
        )
        self._local_takeoff_error_publisher = self.create_publisher(
            Float32,
            '/local_takeoff/error',
            10,
        )
        self._range_subscription = self.create_subscription(
            Range,
            self._input_topic,
            self._range_callback,
            qos_profile_sensor_data,
        )
        self._state_subscription = self.create_subscription(
            State,
            '/mavros/state',
            self._state_callback,
            10,
        )
        self._pose_subscription = self.create_subscription(
            PoseStamped,
            local_position_topic,
            self._pose_callback,
            qos_profile_sensor_data,
        )
        self._velocity_subscription = self.create_subscription(
            TwistStamped,
            local_velocity_topic,
            self._velocity_callback,
            qos_profile_sensor_data,
        )
        self._enable_service = self.create_service(
            SetBool,
            enable_service,
            self._enable_callback,
        )
        self._local_takeoff_enable_service = self.create_service(
            SetBool,
            local_takeoff_enable_service,
            self._local_takeoff_enable_callback,
        )
        self._timer = self.create_timer(
            1.0 / self._control_rate_hz,
            self._control_callback,
        )
        self.get_logger().info(
            'Distance controller ready (default OFF); '
            f'target={self._pid.target_distance_m:.2f} m, '
            f'deadband=+/-{self._pid.deadband_m:.2f} m, '
            f'max_speed={self._pid.max_speed_mps:.2f} m/s'
        )
        self._publish_enabled_state()
        self._publish_target_reached(False)
        self._publish_local_takeoff_enabled_state()
        self._publish_local_takeoff_reached(False)
        self._publish_control_mode()

    def _range_callback(self, message: Range) -> None:
        if math.isfinite(message.range):
            self._latest_distance_m = float(message.range)
            self._last_sensor_time = time.monotonic()

    def _state_callback(self, message: State) -> None:
        self._mavros_connected = bool(message.connected)
        self._mavros_armed = bool(message.armed)
        self._mavros_mode = str(message.mode)

    def _pose_callback(self, message: PoseStamped) -> None:
        local_z_m = float(message.pose.position.z)
        if math.isfinite(local_z_m):
            self._local_z_m = local_z_m
            self._local_z_time = time.monotonic()

    def _velocity_callback(self, message: TwistStamped) -> None:
        vertical_speed_mps = float(message.twist.linear.z)
        if math.isfinite(vertical_speed_mps):
            self._local_vertical_speed_mps = vertical_speed_mps
            self._local_velocity_time = time.monotonic()

    def _enable_callback(
        self,
        request: SetBool.Request,
        response: SetBool.Response,
    ) -> SetBool.Response:
        requested = bool(request.data)
        now = time.monotonic()
        sensor_fresh = (
            self._last_sensor_time is not None
            and now - self._last_sensor_time <= self._sensor_timeout_s
        )
        if requested and not sensor_fresh:
            response.success = False
            response.message = 'cannot enable: distance sensor unavailable or stale'
            return response
        if requested and self._require_mavros and not self._mavros_connected:
            response.success = False
            response.message = 'cannot enable: MAVROS disconnected'
            return response
        if requested and self._require_mavros and not self._mavros_armed:
            response.success = False
            response.message = 'cannot enable: vehicle is disarmed'
            return response

        if requested and self._mode == VerticalControlMode.LOCAL_TAKEOFF:
            response.success = False
            response.message = 'cannot enable: local takeoff control is active'
            return response
        if not requested and self._mode != VerticalControlMode.LIDAR_DISTANCE:
            response.success = True
            response.message = 'already disabled'
            return response

        self._enabled = requested
        self._mode = (
            VerticalControlMode.LIDAR_DISTANCE
            if requested
            else VerticalControlMode.DISABLED
        )
        self._pid.reset()
        self._stability_detector.reset()
        self._publish_target_reached(False)
        self._last_control_time = time.monotonic()
        self._watchdog_active = False
        if not self._enabled:
            self._publish_command(0.0)
        self._publish_enabled_state()
        self._publish_control_mode()
        state_text = 'enabled' if self._enabled else 'disabled'
        self.get_logger().info(f'Distance control {state_text}')
        response.success = True
        response.message = state_text
        return response

    def _local_takeoff_enable_callback(
        self,
        request: SetBool.Request,
        response: SetBool.Response,
    ) -> SetBool.Response:
        requested = bool(request.data)
        now = time.monotonic()
        pose_fresh = (
            self._local_z_time is not None
            and now - self._local_z_time <= self._local_position_timeout_s
            and self._local_z_m is not None
        )
        if requested and self._mode == VerticalControlMode.LIDAR_DISTANCE:
            response.success = False
            response.message = 'cannot enable: distance control is active'
            return response
        if requested and not pose_fresh:
            response.success = False
            response.message = 'cannot enable: local position unavailable or stale'
            return response
        if requested and self._require_mavros and not self._mavros_connected:
            response.success = False
            response.message = 'cannot enable: MAVROS disconnected'
            return response
        if requested and self._require_mavros and not self._mavros_armed:
            response.success = False
            response.message = 'cannot enable: vehicle is disarmed'
            return response
        if not requested and self._mode != VerticalControlMode.LOCAL_TAKEOFF:
            response.success = True
            response.message = 'already disabled'
            return response

        self._local_takeoff_controller.reset()
        self._local_takeoff_stability.reset()
        self._publish_local_takeoff_reached(False)
        self._last_control_time = now
        self._watchdog_active = False
        if requested:
            target_z_m = self._local_takeoff_controller.latch_launch_z(
                self._local_z_m
            )
            self._mode = VerticalControlMode.LOCAL_TAKEOFF
            response.message = f'enabled; target local Z={target_z_m:.3f} m'
        else:
            self._mode = VerticalControlMode.DISABLED
            self._publish_command(0.0)
            response.message = 'disabled'
        self._enabled = False
        self._publish_enabled_state()
        self._publish_local_takeoff_enabled_state()
        self._publish_control_mode()
        self.get_logger().info(f'Local takeoff control {response.message}')
        response.success = True
        return response

    def _publish_enabled_state(self) -> None:
        self._enabled_publisher.publish(Bool(data=self._enabled))

    def _publish_target_reached(self, reached: bool) -> None:
        if reached != self._target_reached:
            state_text = 'reached' if reached else 'lost'
            self.get_logger().info(f'Stable distance target {state_text}')
        self._target_reached = reached
        self._target_reached_publisher.publish(Bool(data=reached))

    def _publish_local_takeoff_enabled_state(self) -> None:
        enabled = self._mode == VerticalControlMode.LOCAL_TAKEOFF
        self._local_takeoff_enabled_publisher.publish(Bool(data=enabled))

    def _publish_local_takeoff_reached(self, reached: bool) -> None:
        if reached != self._local_takeoff_reached:
            state_text = 'reached' if reached else 'lost'
            self.get_logger().info(f'Stable local takeoff target {state_text}')
        self._local_takeoff_reached = reached
        self._local_takeoff_reached_publisher.publish(Bool(data=reached))

    def _publish_control_mode(self) -> None:
        self._control_mode_publisher.publish(String(data=self._mode.value))

    def _publish_command(self, vertical_speed_mps: float) -> None:
        command = TwistStamped()
        command.header.stamp = self.get_clock().now().to_msg()
        command.header.frame_id = self._frame_id
        command.twist.linear.z = vertical_speed_mps
        self._command_publisher.publish(command)
        self._speed_publisher.publish(Float32(data=vertical_speed_mps))

    def _control_callback(self) -> None:
        now = time.monotonic()
        dt = clamp(now - self._last_control_time, 0.001, 0.2)
        self._last_control_time = now
        if self._mode == VerticalControlMode.DISABLED:
            return
        if self._mode == VerticalControlMode.LOCAL_TAKEOFF:
            self._control_local_takeoff(now, dt)
            return

        sensor_stale = (
            self._last_sensor_time is None
            or now - self._last_sensor_time > self._sensor_timeout_s
        )
        mavros_unavailable = self._require_mavros and (
            not self._mavros_connected or not self._mavros_armed
        )
        if sensor_stale or mavros_unavailable or self._latest_distance_m is None:
            self._pid.reset()
            self._stability_detector.reset()
            self._publish_target_reached(False)
            self._publish_command(0.0)
            if not self._watchdog_active:
                if sensor_stale:
                    reason = 'sensor timeout'
                elif not self._mavros_connected:
                    reason = 'MAVROS disconnected'
                else:
                    reason = 'vehicle disarmed'
                self.get_logger().warning(f'Holding zero vertical speed: {reason}')
                self._watchdog_active = True
            return

        self._watchdog_active = False
        speed, error = self._pid.update(self._latest_distance_m, dt)
        self._publish_command(speed)
        self._error_publisher.publish(Float32(data=error))
        flight_state_valid = (
            not self._require_mavros
            or (
                self._mavros_connected
                and self._mavros_armed
                and self._mavros_mode == 'OFFBOARD'
            )
        )
        reached = self._stability_detector.update(
            error_m=error,
            speed_mps=speed,
            now_s=now,
            flight_state_valid=flight_state_valid,
        )
        self._publish_target_reached(reached)

    def _control_local_takeoff(self, now: float, dt: float) -> None:
        pose_stale = (
            self._local_z_time is None
            or now - self._local_z_time > self._local_position_timeout_s
            or self._local_z_m is None
        )
        velocity_stale = (
            self._local_velocity_time is None
            or now - self._local_velocity_time > self._local_position_timeout_s
            or self._local_vertical_speed_mps is None
        )
        mavros_unavailable = self._require_mavros and (
            not self._mavros_connected or not self._mavros_armed
        )
        offboard_inactive = self._require_mavros and self._mavros_mode != 'OFFBOARD'

        # Keep publishing zeros before OFFBOARD so PX4 can accept the mode switch.
        if pose_stale or velocity_stale or mavros_unavailable or offboard_inactive:
            self._local_takeoff_controller.previous_output = 0.0
            self._local_takeoff_stability.reset()
            self._publish_local_takeoff_reached(False)
            self._publish_command(0.0)
            if not self._watchdog_active:
                if pose_stale:
                    reason = 'local position timeout'
                elif velocity_stale:
                    reason = 'local velocity timeout'
                elif not self._mavros_connected:
                    reason = 'MAVROS disconnected'
                elif not self._mavros_armed:
                    reason = 'vehicle disarmed'
                else:
                    reason = 'waiting for OFFBOARD (zero prestream)'
                self.get_logger().warning(f'Holding zero vertical speed: {reason}')
                self._watchdog_active = True
            return

        self._watchdog_active = False
        speed, error = self._local_takeoff_controller.update(self._local_z_m, dt)
        self._publish_command(speed)
        self._local_takeoff_error_publisher.publish(Float32(data=error))
        reached = self._local_takeoff_stability.update(
            error_m=error,
            speed_mps=self._local_vertical_speed_mps,
            now_s=now,
        )
        self._publish_local_takeoff_reached(reached)


def main(args=None) -> None:
    """Run the distance controller node."""
    rclpy.init(args=args)
    node = DistanceControllerNode()
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
