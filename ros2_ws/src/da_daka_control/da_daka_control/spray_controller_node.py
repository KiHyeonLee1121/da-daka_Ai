"""Expose a gated spray trigger service with dry-run as the safe default."""

import json
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger


class SprayControllerNode(Node):
    """Own the spray command endpoint without pretending an unknown HW mapping exists."""

    def __init__(self) -> None:
        super().__init__('spray_controller')
        self.declare_parameter('service_topic', '/spray/trigger')
        self.declare_parameter('active_topic', '/spray/active')
        self.declare_parameter('event_topic', '/spray/last_event')
        self.declare_parameter('pulse_duration_s', 0.30)
        self.declare_parameter('dry_run', True)
        self.declare_parameter('backend', 'dry_run')
        self._service_topic = str(self.get_parameter('service_topic').value)
        active_topic = str(self.get_parameter('active_topic').value)
        event_topic = str(self.get_parameter('event_topic').value)
        self._pulse_duration_s = float(self.get_parameter('pulse_duration_s').value)
        self._dry_run = bool(self.get_parameter('dry_run').value)
        self._backend = str(self.get_parameter('backend').value).lower()
        if not 0.05 <= self._pulse_duration_s <= 2.0:
            raise ValueError('pulse_duration_s must be within [0.05, 2.0]')
        if self._backend not in {'dry_run'}:
            raise ValueError(
                'only backend=dry_run is implemented; configure the real relay/servo '
                'mapping before enabling physical spray'
            )
        if not self._dry_run:
            raise ValueError(
                'physical spray is fail-closed because the Pixhawk relay/servo mapping '
                'is not defined in this repository'
            )

        latched_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._active_publisher = self.create_publisher(Bool, active_topic, latched_qos)
        self._event_publisher = self.create_publisher(String, event_topic, latched_qos)
        self._service = self.create_service(Trigger, self._service_topic, self._trigger)
        self._active_publisher.publish(Bool(data=False))
        self.get_logger().info(
            f'Spray controller ready in DRY-RUN mode; service={self._service_topic}'
        )

    def _trigger(
        self,
        _request: Trigger.Request,
        response: Trigger.Response,
    ) -> Trigger.Response:
        started_ns = time.time_ns()
        self._active_publisher.publish(Bool(data=True))
        event = {
            'backend': self._backend,
            'dry_run': self._dry_run,
            'requested_duration_s': self._pulse_duration_s,
            'timestamp_ns': started_ns,
        }
        self._event_publisher.publish(
            String(data=json.dumps(event, separators=(',', ':')))
        )
        self._active_publisher.publish(Bool(data=False))
        self.get_logger().info(
            f'[DRY-RUN] spray pulse accepted duration={self._pulse_duration_s:.3f}s'
        )
        response.success = True
        response.message = (
            f'dry-run spray pulse accepted ({self._pulse_duration_s:.3f}s); '
            'physical actuator mapping is intentionally disabled'
        )
        return response


def main(args=None) -> None:
    rclpy.init(args=args)
    node = SprayControllerNode()
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
