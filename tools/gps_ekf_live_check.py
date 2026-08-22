#!/usr/bin/env python3
"""Collect a bounded, read-only MAVROS GPS/EKF health snapshot."""

import json
import math
import time

from geometry_msgs.msg import PoseStamped
from mavros_msgs.msg import (
    EstimatorStatus,
    ExtendedState,
    GPSRAW,
    State,
    StatusText,
    SysStatus,
)
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import BatteryState


class LiveCheck(Node):
    """Observe MAVROS telemetry without publishing commands."""

    def __init__(self, duration):
        super().__init__('gps_ekf_live_check')
        self.started = time.monotonic()
        self.duration = duration
        self.gps = []
        self.local_z = []
        self.cpu_load = []
        self.warnings = []
        self.latest = {}
        qos = qos_profile_sensor_data
        self.create_subscription(
            GPSRAW, '/mavros/gpsstatus/gps1/raw', self.on_gps, qos
        )
        self.create_subscription(
            PoseStamped, '/mavros/local_position/pose', self.on_pose, qos
        )
        self.create_subscription(
            StatusText, '/mavros/statustext/recv', self.on_text, qos
        )
        self.create_subscription(State, '/mavros/state', self.on_state, qos)
        self.create_subscription(
            ExtendedState, '/mavros/extended_state', self.on_extended, qos
        )
        self.create_subscription(
            EstimatorStatus,
            '/mavros/estimator_status',
            self.on_estimator,
            qos,
        )
        self.create_subscription(
            BatteryState, '/mavros/battery', self.on_battery, qos
        )
        self.create_subscription(
            SysStatus, '/mavros/sys_status', self.on_sys, qos
        )

    def on_gps(self, msg):
        self.gps.append((time.monotonic() - self.started, msg.alt / 1000.0))
        self.latest['gps'] = {
            'fix_type': msg.fix_type,
            'satellites': msg.satellites_visible,
            'eph_m': None if msg.eph == 65535 else msg.eph / 100.0,
            'epv_m': None if msg.epv == 65535 else msg.epv / 100.0,
            'h_acc_m': None if msg.h_acc == 0 else msg.h_acc / 1000.0,
            'v_acc_m': None if msg.v_acc == 0 else msg.v_acc / 1000.0,
            'altitude_msl_m': msg.alt / 1000.0,
        }

    def on_pose(self, msg):
        self.local_z.append(
            (time.monotonic() - self.started, msg.pose.position.z)
        )
        self.latest['local_z_m'] = msg.pose.position.z

    def on_text(self, msg):
        if msg.severity <= 4:
            self.warnings.append(
                {'severity': msg.severity, 'text': msg.text}
            )

    def on_state(self, msg):
        self.latest.update(
            connected=msg.connected,
            armed=msg.armed,
            mode=msg.mode,
            system_status=msg.system_status,
        )

    def on_extended(self, msg):
        self.latest['landed_state'] = msg.landed_state

    def on_estimator(self, msg):
        self.latest['estimator'] = {
            'horiz_abs': msg.pos_horiz_abs_status_flag,
            'vert_abs': msg.pos_vert_abs_status_flag,
            'gps_glitch': msg.gps_glitch_status_flag,
            'accel_error': msg.accel_error_status_flag,
            'const_pos': msg.const_pos_mode_status_flag,
        }

    def on_battery(self, msg):
        self.latest['battery'] = {
            'voltage_v': msg.voltage,
            'percent': (
                None if math.isnan(msg.percentage) else msg.percentage * 100
            ),
        }

    def on_sys(self, msg):
        self.cpu_load.append(msg.load / 10.0)
        self.latest['comm'] = {
            'drop_rate': msg.drop_rate_comm,
            'errors': msg.errors_comm,
        }

    def result(self):
        def stats(values):
            if not values:
                return None
            samples = [value for _, value in values]
            return {
                'samples': len(samples),
                'start_m': samples[0],
                'end_m': samples[-1],
                'net_change_m': samples[-1] - samples[0],
                'range_m': max(samples) - min(samples),
            }

        cpu = None
        if self.cpu_load:
            cpu = {
                'samples': len(self.cpu_load),
                'min_percent': min(self.cpu_load),
                'max_percent': max(self.cpu_load),
                'last_percent': self.cpu_load[-1],
            }
        return {
            'duration_s': time.monotonic() - self.started,
            'latest': self.latest,
            'gps_altitude': stats(self.gps),
            'local_z': stats(self.local_z),
            'cpu_load': cpu,
            'warnings': self.warnings,
        }


def main():
    rclpy.init()
    node = LiveCheck(65.0)
    while rclpy.ok() and time.monotonic() - node.started < node.duration:
        rclpy.spin_once(node, timeout_sec=0.2)
    print(json.dumps(node.result(), ensure_ascii=False, indent=2))
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
