"""Gate spray on AI target, alignment, distance hold, and low speed."""

import math
import time
from typing import Optional

from da_daka_interfaces.msg import DirtDetection
from geometry_msgs.msg import TwistStamped
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger


class CleaningCoordinatorNode(Node):
    """Coordinate the final stop-to-spray transition without flight commands."""

    def __init__(self) -> None:
        super().__init__('cleaning_coordinator')
        self._declare_parameters()
        self._load_parameters()

        latched_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
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
        self.create_subscription(
            Bool,
            self._distance_target_topic,
            self._distance_callback,
            latched_qos,
        )
        self.create_subscription(
            Bool,
            self._visual_aligned_topic,
            self._aligned_callback,
            latched_qos,
        )
        self.create_subscription(
            Bool,
            self._visual_valid_topic,
            self._visual_valid_callback,
            latched_qos,
        )
        # MAVROS local velocity uses the sensor-data QoS profile.
        self.create_subscription(
            TwistStamped,
            self._velocity_topic,
            self._velocity_callback,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            String,
            self._mission_state_topic,
            self._mission_state_callback,
            latched_qos,
        )
        self._complete_publisher = self.create_publisher(
            Bool,
            self._complete_topic,
            latched_qos,
        )
        self._state_publisher = self.create_publisher(
            String,
            self._state_topic,
            latched_qos,
        )
        self._spray_client = self.create_client(
            Trigger,
            self._spray_service,
        )

        self._ai_healthy = False
        self._detection: Optional[DirtDetection] = None
        self._distance_reached = False
        self._visual_aligned = False
        self._visual_valid = False
        self._vehicle_speed_mps: Optional[float] = None
        self._velocity_time_s: Optional[float] = None
        self._mission_state = 'IDLE'
        self._ready_since_s: Optional[float] = None
        self._request_pending = False
        self._spray_attempts = 0
        self._complete = False
        self._last_state = ''
        self._timer = self.create_timer(1.0 / self._rate_hz, self._tick)
        self._publish_complete(False)
        self._publish_state('WAITING')
        self.get_logger().info(
            'Cleaning coordinator ready; spray requires '
            'AI + alignment + distance + stop'
        )

    def _declare_parameters(self) -> None:
        self.declare_parameter('result_topic', '/ai/detection_result')
        self.declare_parameter('health_topic', '/ai/health')
        self.declare_parameter(
            'distance_target_topic',
            '/distance_control/target_reached',
        )
        self.declare_parameter(
            'visual_aligned_topic',
            '/visual_servo/aligned',
        )
        self.declare_parameter(
            'visual_valid_topic',
            '/visual_servo/target_valid',
        )
        self.declare_parameter(
            'velocity_topic',
            '/mavros/local_position/velocity_local',
        )
        self.declare_parameter('mission_state_topic', '/mission/state')
        self.declare_parameter('complete_topic', '/cleaning/complete')
        self.declare_parameter('state_topic', '/cleaning/state')
        self.declare_parameter('spray_service', '/spray/trigger')
        self.declare_parameter('rate_hz', 20.0)
        self.declare_parameter('max_vehicle_speed_mps', 0.08)
        self.declare_parameter('velocity_timeout_s', 0.5)
        self.declare_parameter('stop_hold_duration_s', 0.20)
        self.declare_parameter('max_spray_attempts', 1)

    def _load_parameters(self) -> None:
        def value(name: str):
            return self.get_parameter(name).value

        self._result_topic = str(value('result_topic'))
        self._health_topic = str(value('health_topic'))
        self._distance_target_topic = str(value('distance_target_topic'))
        self._visual_aligned_topic = str(value('visual_aligned_topic'))
        self._visual_valid_topic = str(value('visual_valid_topic'))
        self._velocity_topic = str(value('velocity_topic'))
        self._mission_state_topic = str(value('mission_state_topic'))
        self._complete_topic = str(value('complete_topic'))
        self._state_topic = str(value('state_topic'))
        self._spray_service = str(value('spray_service'))
        self._rate_hz = float(value('rate_hz'))
        self._max_vehicle_speed_mps = float(
            value('max_vehicle_speed_mps')
        )
        self._velocity_timeout_s = float(value('velocity_timeout_s'))
        self._stop_hold_duration_s = float(
            value('stop_hold_duration_s')
        )
        self._max_spray_attempts = int(value('max_spray_attempts'))
        if min(
            self._rate_hz,
            self._max_vehicle_speed_mps,
            self._velocity_timeout_s,
            self._stop_hold_duration_s,
        ) <= 0.0:
            raise ValueError(
                'cleaning coordinator timing/speed values must be positive'
            )
        if self._max_spray_attempts < 1:
            raise ValueError('max_spray_attempts must be at least one')

    def _detection_callback(self, message: DirtDetection) -> None:
        self._detection = message

    def _health_callback(self, message: Bool) -> None:
        self._ai_healthy = bool(message.data)

    def _distance_callback(self, message: Bool) -> None:
        self._distance_reached = bool(message.data)

    def _aligned_callback(self, message: Bool) -> None:
        self._visual_aligned = bool(message.data)

    def _visual_valid_callback(self, message: Bool) -> None:
        self._visual_valid = bool(message.data)

    def _velocity_callback(self, message: TwistStamped) -> None:
        vx = float(message.twist.linear.x)
        vy = float(message.twist.linear.y)
        vz = float(message.twist.linear.z)
        if all(math.isfinite(value) for value in (vx, vy, vz)):
            self._vehicle_speed_mps = math.sqrt(
                vx * vx + vy * vy + vz * vz
            )
            self._velocity_time_s = time.monotonic()

    def _mission_state_callback(self, message: String) -> None:
        previous = self._mission_state
        self._mission_state = str(message.data)
        reset_states = {'IDLE', 'PRECHECK'}
        if self._mission_state in reset_states:
            if previous != self._mission_state:
                self._reset_cycle()

    def _reset_cycle(self) -> None:
        self._ready_since_s = None
        self._request_pending = False
        self._spray_attempts = 0
        self._complete = False
        self._publish_complete(False)
        self._publish_state('WAITING')

    def _tick(self) -> None:
        if self._complete or self._request_pending:
            return
        now_s = time.monotonic()
        velocity_fresh = (
            self._velocity_time_s is not None
            and now_s - self._velocity_time_s <= self._velocity_timeout_s
            and self._vehicle_speed_mps is not None
        )
        detection_ready = (
            self._detection is not None
            and bool(self._detection.valid)
            and bool(self._detection.dirt_found)
        )
        mission_allows_cleaning = self._mission_state in {
            'DISTANCE_CONTROL',
            'TARGET_HOLD',
        }
        stopped = (
            velocity_fresh
            and self._vehicle_speed_mps <= self._max_vehicle_speed_mps
        )
        ready = (
            mission_allows_cleaning
            and self._ai_healthy
            and detection_ready
            and self._visual_valid
            and self._visual_aligned
            and self._distance_reached
            and stopped
        )
        if not ready:
            self._ready_since_s = None
            self._publish_state('WAITING')
            return
        if self._ready_since_s is None:
            self._ready_since_s = now_s
            self._publish_state('STOP_CONFIRMED')
            return
        if now_s - self._ready_since_s < self._stop_hold_duration_s:
            return
        if self._spray_attempts >= self._max_spray_attempts:
            self._publish_state('SPRAY_FAILED')
            return
        if not self._spray_client.service_is_ready():
            self._publish_state('SPRAY_SERVICE_UNAVAILABLE')
            return

        self._spray_attempts += 1
        self._request_pending = True
        self._publish_state('SPRAY_REQUESTED')
        future = self._spray_client.call_async(Trigger.Request())
        future.add_done_callback(self._spray_done)

    def _spray_done(self, future) -> None:
        self._request_pending = False
        try:
            response = future.result()
        except Exception as exc:  # pragma: no cover - ROS transport failure
            self.get_logger().error(f'spray service failure: {exc}')
            self._publish_state('SPRAY_FAILED')
            return
        if not bool(response.success):
            self.get_logger().error(
                f'spray rejected: {response.message}'
            )
            self._publish_state('SPRAY_FAILED')
            return
        self._complete = True
        self._publish_complete(True)
        self._publish_state('SPRAYED')
        self.get_logger().info(
            f'Cleaning spray completed: {response.message}'
        )

    def _publish_complete(self, value: bool) -> None:
        self._complete_publisher.publish(Bool(data=value))

    def _publish_state(self, state: str) -> None:
        if state == self._last_state:
            return
        self._state_publisher.publish(String(data=state))
        self._last_state = state


def main(args=None) -> None:
    """Run the cleaning coordinator node."""
    rclpy.init(args=args)
    node = CleaningCoordinatorNode()
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
