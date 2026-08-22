#!/usr/bin/env python3
"""Continuously log read-only MAVROS GPS/EKF health warnings."""

from collections import deque
import logging
import time

from geometry_msgs.msg import PoseStamped
from mavros_msgs.msg import GPSRAW, State, StatusText, SysStatus
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data


class Watch(Node):
    """Watch MAVROS telemetry without publishing commands."""

    def __init__(self):
        super().__init__('gps_ekf_watch')
        self.gps_alt = deque()
        self.local_z = deque()
        self.gps = None
        self.state = None
        self.cpu = None
        self.comm = (0, 0)
        self.last_alert = {}
        qos = qos_profile_sensor_data
        self.create_subscription(
            GPSRAW, '/mavros/gpsstatus/gps1/raw', self.on_gps, qos
        )
        self.create_subscription(
            PoseStamped, '/mavros/local_position/pose', self.on_pose, qos
        )
        self.create_subscription(
            SysStatus, '/mavros/sys_status', self.on_sys, qos
        )
        self.create_subscription(
            StatusText, '/mavros/statustext/recv', self.on_text, qos
        )
        self.create_subscription(State, '/mavros/state', self.on_state, qos)
        self.create_timer(5.0, self.check)

    def trim(self, values, now):
        while values and now - values[0][0] > 60.0:
            values.popleft()

    def alert(self, key, message, cooldown=30.0):
        now = time.monotonic()
        if now - self.last_alert.get(key, 0) >= cooldown:
            logging.error('ALERT %s', message)
            self.last_alert[key] = now

    def on_gps(self, msg):
        now = time.monotonic()
        self.gps = msg
        self.gps_alt.append((now, msg.alt / 1000.0))
        self.trim(self.gps_alt, now)

    def on_pose(self, msg):
        now = time.monotonic()
        self.local_z.append((now, msg.pose.position.z))
        self.trim(self.local_z, now)

    def on_sys(self, msg):
        self.cpu = msg.load / 10.0
        self.comm = (msg.drop_rate_comm, msg.errors_comm)

    def on_text(self, msg):
        if msg.severity <= 4:
            self.alert(
                'text:' + msg.text,
                f'FCU severity={msg.severity}: {msg.text}',
                10.0,
            )

    def on_state(self, msg):
        self.state = msg

    def check(self):
        if self.state is None or not self.state.connected:
            self.alert('disconnect', 'Pixhawk MAVROS disconnected')
            return
        if self.gps is None:
            self.alert('gps_missing', 'GPS data missing')
            return
        if self.gps.fix_type < 3:
            self.alert('fix', f'GPS fix degraded: type={self.gps.fix_type}')
        if self.gps.satellites_visible < 10:
            self.alert(
                'sat',
                f'GPS satellites low: {self.gps.satellites_visible}',
            )
        gps_range = None
        if self.gps_alt and self.gps_alt[-1][0] - self.gps_alt[0][0] >= 55:
            values = [value for _, value in self.gps_alt]
            gps_range = max(values) - min(values)
            if gps_range > 0.5:
                self.alert(
                    'gps_drift',
                    f'60s GPS altitude range={gps_range:.3f}m > 0.5m',
                )
        z_range = None
        if self.local_z and self.local_z[-1][0] - self.local_z[0][0] >= 55:
            values = [value for _, value in self.local_z]
            z_range = max(values) - min(values)
            if z_range > 0.5:
                self.alert(
                    'local_z',
                    f'60s EKF local Z range={z_range:.3f}m > 0.5m',
                )
        if self.cpu is not None and self.cpu >= 90:
            self.alert('cpu', f'Pixhawk CPU load high: {self.cpu:.1f}%')
        if self.comm != (0, 0):
            self.alert('comm', f'MAVLink drop/errors={self.comm}')
        logging.info(
            'STATUS armed=%s fix=%d sats=%d eph=%.2fm epv=%.2fm '
            'gps60=%s z60=%s cpu=%s',
            self.state.armed,
            self.gps.fix_type,
            self.gps.satellites_visible,
            self.gps.eph / 100.0,
            self.gps.epv / 100.0,
            'warming' if gps_range is None else f'{gps_range:.3f}m',
            'warming' if z_range is None else f'{z_range:.3f}m',
            'unknown' if self.cpu is None else f'{self.cpu:.1f}%',
        )


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('/workspace/logs/gps_ekf_realtime.log'),
        ],
    )
    rclpy.init()
    node = Watch()
    rclpy.spin(node)


if __name__ == '__main__':
    main()
