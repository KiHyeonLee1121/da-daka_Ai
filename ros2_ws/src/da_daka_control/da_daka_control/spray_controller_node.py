"""ROS 2 services for the fail-closed DA-DAKA spray valve."""

import json

from da_daka_control.spray_actuator import (
    GpioValveBackend,
    MockValveBackend,
    TimedSprayController,
)
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Bool, String
from std_srvs.srv import SetBool, Trigger


class SprayControllerNode(Node):
    """Expose enable/trigger/stop without owning flight movement."""

    def __init__(self) -> None:
        super().__init__('spray_controller')
        self._declare_parameters()
        backend_name = str(self.get_parameter('backend').value).lower()
        output_enabled = bool(self.get_parameter('output_enabled').value)
        if backend_name == 'gpio':
            backend = GpioValveBackend(
                str(self.get_parameter('gpio_chip').value),
                int(self.get_parameter('gpio_line_offset').value),
                bool(self.get_parameter('active_high').value),
            )
        elif backend_name == 'mock':
            backend = MockValveBackend()
        else:
            raise ValueError(f'unsupported spray backend: {backend_name}')
        self._controller = TimedSprayController(
            backend,
            output_enabled=output_enabled,
            pulse_duration_s=float(
                self.get_parameter('pulse_duration_s').value
            ),
            minimum_pulse_s=float(
                self.get_parameter('minimum_pulse_s').value
            ),
            maximum_pulse_s=float(
                self.get_parameter('maximum_pulse_s').value
            ),
            cooldown_s=float(self.get_parameter('cooldown_s').value),
            maximum_pulses=int(
                self.get_parameter('maximum_pulses_per_session').value
            ),
        )
        status_rate_hz = float(self.get_parameter('status_rate_hz').value)
        if status_rate_hz <= 0.0:
            raise ValueError('status_rate_hz must be positive')
        self._active_publisher = self.create_publisher(
            Bool, '/spray/active', 10
        )
        self._status_publisher = self.create_publisher(
            String, '/spray/status', 10
        )
        self.create_service(SetBool, '/spray/enable', self._enable)
        self.create_service(Trigger, '/spray/trigger', self._trigger)
        self.create_service(Trigger, '/spray/stop', self._stop)
        self._timer = self.create_timer(
            1.0 / status_rate_hz,
            self._publish_status,
        )
        mode = 'LIVE' if output_enabled else 'BLOCKED'
        self.get_logger().info(
            f'Spray controller backend={backend_name}, output={mode}'
        )

    def _declare_parameters(self) -> None:
        self.declare_parameter('backend', 'mock')
        self.declare_parameter('output_enabled', False)
        self.declare_parameter('gpio_chip', '')
        self.declare_parameter('gpio_line_offset', -1)
        self.declare_parameter('active_high', True)
        self.declare_parameter('pulse_duration_s', 0.30)
        self.declare_parameter('minimum_pulse_s', 0.05)
        self.declare_parameter('maximum_pulse_s', 1.00)
        self.declare_parameter('cooldown_s', 2.0)
        self.declare_parameter('maximum_pulses_per_session', 3)
        self.declare_parameter('status_rate_hz', 10.0)

    def _enable(self, request, response):
        result = self._controller.set_enabled(bool(request.data))
        response.success = result.success
        response.message = result.message
        self._publish_status()
        return response

    def _trigger(self, _request, response):
        result = self._controller.trigger()
        response.success = result.success
        response.message = result.message
        self._publish_status()
        return response

    def _stop(self, _request, response):
        result = self._controller.stop()
        response.success = result.success
        response.message = result.message
        self._publish_status()
        return response

    def _publish_status(self) -> None:
        status = self._controller.status()
        self._active_publisher.publish(Bool(data=status.active))
        self._status_publisher.publish(
            String(
                data=json.dumps(
                    {
                        'output_enabled': status.output_enabled,
                        'session_enabled': status.session_enabled,
                        'active': status.active,
                        'pulse_count': status.pulse_count,
                        'maximum_pulses': status.maximum_pulses,
                        'backend': status.backend,
                    },
                    separators=(',', ':'),
                )
            )
        )

    def destroy_node(self) -> bool:
        """Force the valve closed before destroying the ROS node."""
        self._controller.close()
        return super().destroy_node()


def main(args=None) -> None:
    """Run the spray controller node."""
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
