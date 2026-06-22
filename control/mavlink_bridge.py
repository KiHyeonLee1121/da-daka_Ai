from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class MavlinkBridge:
    """Safe Pixhawk/MAVLink bridge.

    Dry-run is the default. Live mode requires explicit configuration and must
    be tested without propellers, in SITL, and under restraint before flight.
    """

    def __init__(self, mavlink_config: dict[str, Any]):
        self.dry_run = bool(mavlink_config.get("dry_run", True))
        self.connection_string = str(mavlink_config.get("connection_string", "udp:127.0.0.1:14550"))
        self.baudrate = int(mavlink_config.get("baudrate", 57600))
        self.master = None

    def connect(self) -> None:
        if self.dry_run:
            logger.info("[DRY-RUN] MAVLink connect skipped: %s", self.connection_string)
            return

        from pymavlink import mavutil

        self.master = mavutil.mavlink_connection(self.connection_string, baud=self.baudrate)
        self.master.wait_heartbeat(timeout=10)
        logger.info("Connected to MAVLink system=%s component=%s", self.master.target_system, self.master.target_component)

    def is_connected(self) -> bool:
        return self.dry_run or self.master is not None

    def send_velocity_setpoint(self, vx: float, vy: float, vz: float, yaw_rate: float = 0.0) -> None:
        if self.dry_run:
            logger.info("[DRY-RUN] velocity setpoint vx=%.3f vy=%.3f vz=%.3f yaw_rate=%.3f", vx, vy, vz, yaw_rate)
            return

        if self.master is None:
            raise RuntimeError("MAVLink is not connected")

        from pymavlink import mavutil

        # Velocity-only BODY_NED setpoint. Confirm frame/sign conventions on the real aircraft.
        type_mask = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 6) | (1 << 7) | (1 << 8) | (1 << 10)
        self.master.mav.set_position_target_local_ned_send(
            0,
            self.master.target_system,
            self.master.target_component,
            mavutil.mavlink.MAV_FRAME_BODY_NED,
            type_mask,
            0,
            0,
            0,
            vx,
            vy,
            vz,
            0,
            0,
            0,
            0,
            yaw_rate,
        )

    def send_hold(self) -> None:
        logger.info("send_hold")
        self.send_velocity_setpoint(0.0, 0.0, 0.0, 0.0)

    def send_stop(self) -> None:
        logger.info("send_stop")
        self.send_velocity_setpoint(0.0, 0.0, 0.0, 0.0)

    def send_spray_trigger(self, duration_s: float) -> None:
        if self.dry_run:
            logger.info("[DRY-RUN] spray trigger duration=%.3fs", duration_s)
            return

        # The exact actuator command depends on Pixhawk output mapping
        # (relay, servo PWM, or custom actuator function). Keep live spray
        # disabled until that mapping is configured and bench-tested.
        logger.warning("Live MAVLink spray trigger is not configured. duration=%.3fs", duration_s)

    def close(self) -> None:
        if self.master is not None:
            self.master.close()
            self.master = None
