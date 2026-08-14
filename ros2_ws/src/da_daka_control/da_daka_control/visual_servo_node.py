"""Convert validated laptop dirt coordinates into bounded horizontal corrections."""

import math
import time
from typing import Optional

from da_daka_interfaces.msg import DirtDetection
from geometry_msgs.msg import TwistStamped
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool


def clamp(value: float, limit: float) -> float:
    """Clamp a signed value to +/-limit."""
    return min(max(value, -limit), limit)


def compute_visual_velocity(
    *,
    centroid_x_norm: float,
    centroid_y_norm: float,
    horizontal_deadband_norm: float,
    vertical_deadband_norm: float,
    kp_horizontal: float,
    kp_vertical: float,
    max_horizontal_speed_mps: float,
    max_vertical_image_speed_mps: float,
    invert_horizontal: bool,
    invert_vertical: bool,
) -> tuple[float, float, bool]:
    """Return image-horizontal/image-vertical velocity corrections and alignment."""
    error_x = centroid_x_norm - 0.5
    error_y = centroid_y_norm - 0.5
    aligned = (
        abs(error_x) <= horizontal_deadband_norm
        and abs(error_y) <= vertical_deadband_norm
    )
    if aligned:
        return 0.0, 0.0, True

    horizontal = 0.0
    vertical = 0.0
    if abs(error_x) > horizontal_deadband_norm:
        horizontal = clamp(kp_horizontal * error_x, max_horizontal_speed_mps)
    if abs(error_y) > vertical_deadband_norm:
        vertical = clamp(kp_vertical * error_y, max_vertical_image_speed_mps)
    if invert_horizontal:
        horizontal *= -1.0
    if invert_vertical:
        vertical *= -1.0
    return horizontal, vertical, False


class VisualServoNode(Node):
    """Publish AI-derived XY correction only; never publish MAVROS setpoints directly."""

    def __init__(self) -> None:
        super().__init__('visual_servo')
        self._declare_parameters()
        self._load_parameters()

        latched_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._command_publisher = self.create_publisher(
            TwistStamped,
            self._command_topic,
            10,
        )
        self._aligned_publisher = self.create_publisher(
            Bool,
            self._aligned_topic,
            latched_qos,
        )
        self._valid_publisher = self.create_publisher(
            Bool,
            self._target_valid_topic,
            latched_qos,
        )
        self.create_subscription(
            DirtDetection,
            self._result_topic,
            self._detection_callback,
            latched_qos,
        )
        self.create_subscription(
            Bool,
            self._health_topic,
            self._health_callback,
            latched_qos,
        )

        self._ai_healthy = False
        self._detection: Optional[DirtDetection] = None
        self._last_detection_time_s: Optional[float] = None
        self._last_aligned: Optional[bool] = None
        self._last_valid: Optional[bool] = None
        self._timer = self.create_timer(1.0 / self._control_rate_hz, self._tick)
        self._publish_state(False, False)
        self.get_logger().info(
            'Visual servo ready; AI coordinates -> bounded XY correction only'
        )

    def _declare_parameters(self) -> None:
        self.declare_parameter('result_topic', '/ai/detection_result')
        self.declare_parameter('health_topic', '/ai/health')
        self.declare_parameter('command_topic', '/visual_servo/cmd_vel_xy')
        self.declare_parameter('aligned_topic', '/visual_servo/aligned')
        self.declare_parameter('target_valid_topic', '/visual_servo/target_valid')
        self.declare_parameter('frame_id', 'map')
        self.declare_parameter('control_rate_hz', 20.0)
        self.declare_parameter('target_timeout_s', 0.5)
        self.declare_parameter('horizontal_deadband_norm', 0.04)
        self.declare_parameter('vertical_deadband_norm', 0.04)
        self.declare_parameter('kp_horizontal', 0.35)
        self.declare_parameter('kp_vertical', 0.35)
        self.declare_parameter('max_horizontal_speed_mps', 0.12)
        self.declare_parameter('max_vertical_image_speed_mps', 0.12)
        self.declare_parameter('horizontal_axis', 'y')
        self.declare_parameter('vertical_axis', 'x')
        self.declare_parameter('invert_horizontal', False)
        self.declare_parameter('invert_vertical', True)

    def _load_parameters(self) -> None:
        value = lambda name: self.get_parameter(name).value
        self._result_topic = str(value('result_topic'))
        self._health_topic = str(value('health_topic'))
        self._command_topic = str(value('command_topic'))
        self._aligned_topic = str(value('aligned_topic'))
        self._target_valid_topic = str(value('target_valid_topic'))
        self._frame_id = str(value('frame_id'))
        self._control_rate_hz = float(value('control_rate_hz'))
        self._target_timeout_s = float(value('target_timeout_s'))
        self._horizontal_deadband_norm = float(value('horizontal_deadband_norm'))
        self._vertical_deadband_norm = float(value('vertical_deadband_norm'))
        self._kp_horizontal = float(value('kp_horizontal'))
        self._kp_vertical = float(value('kp_vertical'))
        self._max_horizontal_speed_mps = float(value('max_horizontal_speed_mps'))
        self._max_vertical_image_speed_mps = float(value('max_vertical_image_speed_mps'))
        self._horizontal_axis = str(value('horizontal_axis')).lower()
        self._vertical_axis = str(value('vertical_axis')).lower()
        self._invert_horizontal = bool(value('invert_horizontal'))
        self._invert_vertical = bool(value('invert_vertical'))
        if self._control_rate_hz <= 0.0 or self._target_timeout_s <= 0.0:
            raise ValueError('visual servo rates/timeouts must be positive')
        if not 0.0 <= self._horizontal_deadband_norm < 0.5:
            raise ValueError('horizontal_deadband_norm must be within [0, 0.5)')
        if not 0.0 <= self._vertical_deadband_norm < 0.5:
            raise ValueError('vertical_deadband_norm must be within [0, 0.5)')
        if min(self._kp_horizontal, self._kp_vertical) < 0.0:
            raise ValueError('visual servo gains cannot be negative')
        if min(self._max_horizontal_speed_mps, self._max_vertical_image_speed_mps) <= 0.0:
            raise ValueError('visual servo speed limits must be positive')
        if {self._horizontal_axis, self._vertical_axis} != {'x', 'y'}:
            raise ValueError('horizontal_axis and vertical_axis must be distinct x/y axes')

    def _health_callback(self, message: Bool) -> None:
        self._ai_healthy = bool(message.data)

    def _detection_callback(self, message: DirtDetection) -> None:
        self._detection = message
        self._last_detection_time_s = time.monotonic()

    def _tick(self) -> None:
        now_s = time.monotonic()
        target_valid = (
            self._ai_healthy
            and self._detection is not None
            and self._last_detection_time_s is not None
            and now_s - self._last_detection_time_s <= self._target_timeout_s
            and bool(self._detection.valid)
            and bool(self._detection.dirt_found)
            and math.isfinite(float(self._detection.centroid_x_norm))
            and math.isfinite(float(self._detection.centroid_y_norm))
        )
        command = TwistStamped()
        command.header.stamp = self.get_clock().now().to_msg()
        command.header.frame_id = self._frame_id
        aligned = False
        if target_valid:
            horizontal, vertical, aligned = compute_visual_velocity(
                centroid_x_norm=float(self._detection.centroid_x_norm),
                centroid_y_norm=float(self._detection.centroid_y_norm),
                horizontal_deadband_norm=self._horizontal_deadband_norm,
                vertical_deadband_norm=self._vertical_deadband_norm,
                kp_horizontal=self._kp_horizontal,
                kp_vertical=self._kp_vertical,
                max_horizontal_speed_mps=self._max_horizontal_speed_mps,
                max_vertical_image_speed_mps=self._max_vertical_image_speed_mps,
                invert_horizontal=self._invert_horizontal,
                invert_vertical=self._invert_vertical,
            )
            self._assign_axis(command, self._horizontal_axis, horizontal)
            self._assign_axis(command, self._vertical_axis, vertical)
        self._command_publisher.publish(command)
        self._publish_state(aligned, target_valid)

    @staticmethod
    def _assign_axis(message: TwistStamped, axis: str, value: float) -> None:
        if axis == 'x':
            message.twist.linear.x = value
        elif axis == 'y':
            message.twist.linear.y = value

    def _publish_state(self, aligned: bool, valid: bool) -> None:
        if aligned != self._last_aligned:
            self._aligned_publisher.publish(Bool(data=aligned))
            self._last_aligned = aligned
        if valid != self._last_valid:
            self._valid_publisher.publish(Bool(data=valid))
            self._last_valid = valid


def main(args=None) -> None:
    rclpy.init(args=args)
    node = VisualServoNode()
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
