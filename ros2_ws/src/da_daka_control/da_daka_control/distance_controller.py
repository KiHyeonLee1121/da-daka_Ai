"""Generate a limited vertical MAVROS velocity from filtered distance."""

import math
import time
from typing import Optional

import rclpy
from geometry_msgs.msg import TwistStamped
from mavros_msgs.msg import State
from mavros_msgs.srv import SetMode
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Range
from std_msgs.msg import Bool, Float32
from std_srvs.srv import SetBool


def clamp(value: float, lower: float, upper: float) -> float:
    """Clamp value to the inclusive lower and upper limits."""
    return min(max(value, lower), upper)


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
            raise ValueError("target_distance_m must be greater than zero")
        if deadband_m < 0.0:
            raise ValueError("deadband_m cannot be negative")
        if integral_limit < 0.0:
            raise ValueError("integral_limit cannot be negative")
        if max_speed_mps <= 0.0:
            raise ValueError("max_speed_mps must be greater than zero")
        if slow_zone_m <= 0.0:
            raise ValueError("slow_zone_m must be greater than zero")
        if max_accel_mps2 <= 0.0:
            raise ValueError("max_accel_mps2 must be greater than zero")
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
            raise ValueError("dt must be greater than zero")

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
            raise ValueError("tolerance_m must be greater than zero")
        if duration_s <= 0.0:
            raise ValueError("duration_s must be greater than zero")
        if max_speed_mps < 0.0:
            raise ValueError("max_speed_mps cannot be negative")
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
    """Publish vertical velocity only while distance control is enabled."""

    def __init__(self) -> None:
        super().__init__("distance_controller")
        self.declare_parameter("input_topic", "/distance/filtered")
        self.declare_parameter("command_topic", "/mavros/setpoint_velocity/cmd_vel")
        self.declare_parameter("enable_service", "/distance_control/enable")
        self.declare_parameter("enabled_state_topic", "/distance_control/enabled")
        self.declare_parameter(
            "target_reached_topic",
            "/distance_control/target_reached",
        )
        self.declare_parameter("frame_id", "map")
        self.declare_parameter("control_rate_hz", 20.0)
        self.declare_parameter("enabled_on_startup", False)
        self.declare_parameter("require_mavros_connected", True)
        self.declare_parameter("sensor_timeout_s", 0.3)
        self.declare_parameter("target_distance_m", 1.0)
        self.declare_parameter("deadband_m", 0.05)
        self.declare_parameter("kp", 0.6)
        self.declare_parameter("ki", 0.0)
        self.declare_parameter("kd", 0.0)
        self.declare_parameter("integral_limit", 0.3)
        self.declare_parameter("max_vertical_speed_mps", 0.25)
        self.declare_parameter("slow_zone_m", 0.30)
        self.declare_parameter("max_vertical_accel_mps2", 0.5)
        self.declare_parameter("target_stable_tolerance_m", 0.05)
        self.declare_parameter("target_stable_duration_s", 5.0)
        self.declare_parameter("target_stable_max_speed_mps", 0.05)
        self.declare_parameter("auto_disable_on_target_reached", True)
        self.declare_parameter("auto_disable_handoff_mode", "AUTO.LOITER")

        self._input_topic = str(self.get_parameter("input_topic").value)
        command_topic = str(self.get_parameter("command_topic").value)
        enable_service = str(self.get_parameter("enable_service").value)
        enabled_state_topic = str(self.get_parameter("enabled_state_topic").value)
        target_reached_topic = str(
            self.get_parameter("target_reached_topic").value
        )
        self._frame_id = str(self.get_parameter("frame_id").value)
        self._control_rate_hz = float(self.get_parameter("control_rate_hz").value)
        self._enabled = bool(self.get_parameter("enabled_on_startup").value)
        self._require_mavros = bool(
            self.get_parameter("require_mavros_connected").value
        )
        self._sensor_timeout_s = float(self.get_parameter("sensor_timeout_s").value)

        if self._control_rate_hz <= 0.0:
            raise ValueError("control_rate_hz must be greater than zero")
        if self._sensor_timeout_s <= 0.0:
            raise ValueError("sensor_timeout_s must be greater than zero")

        self._pid = DistancePid(
            target_distance_m=float(self.get_parameter("target_distance_m").value),
            deadband_m=float(self.get_parameter("deadband_m").value),
            kp=float(self.get_parameter("kp").value),
            ki=float(self.get_parameter("ki").value),
            kd=float(self.get_parameter("kd").value),
            integral_limit=float(self.get_parameter("integral_limit").value),
            max_speed_mps=float(
                self.get_parameter("max_vertical_speed_mps").value
            ),
            slow_zone_m=float(self.get_parameter("slow_zone_m").value),
            max_accel_mps2=float(
                self.get_parameter("max_vertical_accel_mps2").value
            ),
        )
        self._stability_detector = TargetStabilityDetector(
            tolerance_m=float(
                self.get_parameter("target_stable_tolerance_m").value
            ),
            duration_s=float(
                self.get_parameter("target_stable_duration_s").value
            ),
            max_speed_mps=float(
                self.get_parameter("target_stable_max_speed_mps").value
            ),
        )
        self._auto_disable_on_target = bool(
            self.get_parameter("auto_disable_on_target_reached").value
        )
        self._handoff_mode = str(
            self.get_parameter("auto_disable_handoff_mode").value
        )
        if self._auto_disable_on_target and not self._handoff_mode:
            raise ValueError(
                "auto_disable_handoff_mode cannot be empty when auto-disable is enabled"
            )

        self._latest_distance_m: Optional[float] = None
        self._last_sensor_time: Optional[float] = None
        self._last_control_time = time.monotonic()
        self._mavros_connected = False
        self._mavros_armed = False
        self._mavros_mode = ""
        self._watchdog_active = False
        self._target_reached = False
        self._handoff_requested = False
        self._handoff_request_time = 0.0

        self._command_publisher = self.create_publisher(
            TwistStamped,
            command_topic,
            qos_profile_sensor_data,
        )
        self._error_publisher = self.create_publisher(
            Float32,
            "/distance_control/error",
            10,
        )
        self._speed_publisher = self.create_publisher(
            Float32,
            "/distance_control/vertical_speed_cmd",
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
        self._range_subscription = self.create_subscription(
            Range,
            self._input_topic,
            self._range_callback,
            qos_profile_sensor_data,
        )
        self._state_subscription = self.create_subscription(
            State,
            "/mavros/state",
            self._state_callback,
            10,
        )
        self._enable_service = self.create_service(
            SetBool,
            enable_service,
            self._enable_callback,
        )
        self._set_mode_client = self.create_client(SetMode, "/mavros/set_mode")
        self._timer = self.create_timer(
            1.0 / self._control_rate_hz,
            self._control_callback,
        )
        self.get_logger().info(
            "Distance controller ready (default OFF); "
            f"target={self._pid.target_distance_m:.2f} m, "
            f"deadband=+/-{self._pid.deadband_m:.2f} m, "
            f"max_speed={self._pid.max_speed_mps:.2f} m/s"
        )
        self._publish_enabled_state()
        self._publish_target_reached(False)

    def _range_callback(self, message: Range) -> None:
        if math.isfinite(message.range):
            self._latest_distance_m = float(message.range)
            self._last_sensor_time = time.monotonic()

    def _state_callback(self, message: State) -> None:
        self._mavros_connected = bool(message.connected)
        self._mavros_armed = bool(message.armed)
        self._mavros_mode = str(message.mode)
        if (
            self._enabled
            and self._target_reached
            and self._handoff_requested
            and self._mavros_mode == self._handoff_mode
        ):
            self._complete_target_handoff()

    def _enable_callback(
        self,
        request: SetBool.Request,
        response: SetBool.Response,
    ) -> SetBool.Response:
        self._enabled = bool(request.data)
        self._pid.reset()
        self._stability_detector.reset()
        self._handoff_requested = False
        self._publish_target_reached(False)
        self._last_control_time = time.monotonic()
        self._watchdog_active = False
        if not self._enabled:
            self._publish_command(0.0)
        self._publish_enabled_state()
        state_text = "enabled" if self._enabled else "disabled"
        self.get_logger().info(f"Distance control {state_text}")
        response.success = True
        response.message = state_text
        return response

    def _publish_enabled_state(self) -> None:
        self._enabled_publisher.publish(Bool(data=self._enabled))

    def _publish_target_reached(self, reached: bool) -> None:
        if reached != self._target_reached:
            state_text = "reached" if reached else "lost"
            self.get_logger().info(f"Stable distance target {state_text}")
        self._target_reached = reached
        self._target_reached_publisher.publish(Bool(data=reached))

    def _request_target_handoff(self, now_s: float) -> None:
        """Request a safe PX4 hold mode before stopping OFFBOARD commands."""
        if self._mavros_mode == self._handoff_mode:
            self._handoff_requested = True
            self._complete_target_handoff()
            return
        if self._handoff_requested:
            return
        if now_s - self._handoff_request_time < 1.0:
            return
        self._handoff_request_time = now_s
        if not self._set_mode_client.service_is_ready():
            self.get_logger().warning(
                "Target reached, but /mavros/set_mode is unavailable; "
                "keeping distance control enabled"
            )
            return
        request = SetMode.Request()
        request.base_mode = 0
        request.custom_mode = self._handoff_mode
        self._handoff_requested = True
        future = self._set_mode_client.call_async(request)
        future.add_done_callback(self._handoff_response_callback)
        self.get_logger().info(
            f"Target reached; requesting {self._handoff_mode} before auto-disable"
        )

    def _handoff_response_callback(self, future) -> None:
        try:
            response = future.result()
        except Exception as error:  # pragma: no cover - ROS transport failure
            self.get_logger().error(f"Mode handoff request failed: {error}")
            self._handoff_requested = False
            return
        if not response.mode_sent:
            self.get_logger().warning(
                f"PX4 rejected {self._handoff_mode}; "
                "keeping distance control enabled"
            )
            self._handoff_requested = False

    def _complete_target_handoff(self) -> None:
        """Disable distance correction only after PX4 confirms hold mode."""
        if not self._enabled:
            return
        self._enabled = False
        self._pid.reset()
        self._stability_detector.reset()
        self._publish_command(0.0)
        self._publish_enabled_state()
        self.get_logger().info(
            f"PX4 confirmed {self._handoff_mode}; distance control auto-disabled"
        )

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
        if not self._enabled:
            return

        sensor_stale = (
            self._last_sensor_time is None
            or now - self._last_sensor_time > self._sensor_timeout_s
        )
        mavros_unavailable = self._require_mavros and not self._mavros_connected
        if sensor_stale or mavros_unavailable or self._latest_distance_m is None:
            self._pid.reset()
            self._stability_detector.reset()
            self._publish_target_reached(False)
            self._publish_command(0.0)
            if not self._watchdog_active:
                reason = "sensor timeout" if sensor_stale else "MAVROS disconnected"
                self.get_logger().warning(f"Holding zero vertical speed: {reason}")
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
                and self._mavros_mode == "OFFBOARD"
            )
        )
        reached = self._stability_detector.update(
            error_m=error,
            speed_mps=speed,
            now_s=now,
            flight_state_valid=flight_state_valid,
        )
        self._publish_target_reached(reached)
        if reached and self._auto_disable_on_target:
            self._request_target_handoff(now)


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


if __name__ == "__main__":
    main()
