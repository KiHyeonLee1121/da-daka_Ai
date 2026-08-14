"""Merge LiDAR Z control and AI visual XY correction into one MAVROS setpoint."""

import time
from typing import Optional

from geometry_msgs.msg import TwistStamped
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool


class ControlCommandMixerNode(Node):
    """Remain the only cleaning-stack publisher to MAVROS velocity setpoints.

    Distance control publishes an intermediate Z command and visual servo publishes
    an intermediate XY command. This node combines them, preventing two independent
    nodes from racing on /mavros/setpoint_velocity/cmd_vel.
    """

    def __init__(self) -> None:
        super().__init__('control_command_mixer')
        self._declare_parameters()
        self._load_parameters()
        self._distance_command: Optional[TwistStamped] = None
        self._distance_time_s: Optional[float] = None
        self._visual_command: Optional[TwistStamped] = None
        self._visual_time_s: Optional[float] = None
        self._visual_target_valid = False
        self._last_healthy: Optional[bool] = None

        self._publisher = self.create_publisher(
            TwistStamped,
            self._output_topic,
            10,
        )
        latched_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._health_publisher = self.create_publisher(
            Bool,
            self._health_topic,
            latched_qos,
        )
        self.create_subscription(
            TwistStamped,
            self._distance_command_topic,
            self._distance_callback,
            10,
        )
        self.create_subscription(
            TwistStamped,
            self._visual_command_topic,
            self._visual_callback,
            10,
        )
        self.create_subscription(
            Bool,
            self._visual_target_valid_topic,
            self._valid_callback,
            latched_qos,
        )
        self._timer = self.create_timer(1.0 / self._publish_rate_hz, self._tick)
        self.get_logger().info(
            f'Control mixer ready; sole MAVROS velocity output={self._output_topic}'
        )

    def _declare_parameters(self) -> None:
        self.declare_parameter('distance_command_topic', '/distance_control/cmd_vel_z')
        self.declare_parameter('visual_command_topic', '/visual_servo/cmd_vel_xy')
        self.declare_parameter('visual_target_valid_topic', '/visual_servo/target_valid')
        self.declare_parameter('output_topic', '/mavros/setpoint_velocity/cmd_vel')
        self.declare_parameter('health_topic', '/control_mixer/healthy')
        self.declare_parameter('frame_id', 'map')
        self.declare_parameter('publish_rate_hz', 20.0)
        self.declare_parameter('distance_command_timeout_s', 0.3)
        self.declare_parameter('visual_command_timeout_s', 0.3)
        self.declare_parameter('require_visual_target', True)

    def _load_parameters(self) -> None:
        value = lambda name: self.get_parameter(name).value
        self._distance_command_topic = str(value('distance_command_topic'))
        self._visual_command_topic = str(value('visual_command_topic'))
        self._visual_target_valid_topic = str(value('visual_target_valid_topic'))
        self._output_topic = str(value('output_topic'))
        self._health_topic = str(value('health_topic'))
        self._frame_id = str(value('frame_id'))
        self._publish_rate_hz = float(value('publish_rate_hz'))
        self._distance_timeout_s = float(value('distance_command_timeout_s'))
        self._visual_timeout_s = float(value('visual_command_timeout_s'))
        self._require_visual_target = bool(value('require_visual_target'))
        if min(self._publish_rate_hz, self._distance_timeout_s, self._visual_timeout_s) <= 0.0:
            raise ValueError('control mixer rates/timeouts must be positive')

    def _distance_callback(self, message: TwistStamped) -> None:
        self._distance_command = message
        self._distance_time_s = time.monotonic()

    def _visual_callback(self, message: TwistStamped) -> None:
        self._visual_command = message
        self._visual_time_s = time.monotonic()

    def _valid_callback(self, message: Bool) -> None:
        self._visual_target_valid = bool(message.data)

    def _tick(self) -> None:
        now_s = time.monotonic()
        distance_fresh = (
            self._distance_command is not None
            and self._distance_time_s is not None
            and now_s - self._distance_time_s <= self._distance_timeout_s
        )
        visual_fresh = (
            self._visual_command is not None
            and self._visual_time_s is not None
            and now_s - self._visual_time_s <= self._visual_timeout_s
        )
        visual_ready = visual_fresh and (
            self._visual_target_valid or not self._require_visual_target
        )
        healthy = distance_fresh and visual_ready

        output = TwistStamped()
        output.header.stamp = self.get_clock().now().to_msg()
        output.header.frame_id = self._frame_id
        if healthy:
            output.twist.linear.x = self._visual_command.twist.linear.x
            output.twist.linear.y = self._visual_command.twist.linear.y
            output.twist.linear.z = self._distance_command.twist.linear.z
            output.twist.angular.z = self._visual_command.twist.angular.z
        self._publisher.publish(output)
        if healthy != self._last_healthy:
            self._health_publisher.publish(Bool(data=healthy))
            self._last_healthy = healthy
            self.get_logger().info(f'Control mixer healthy={healthy}')


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ControlCommandMixerNode()
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
