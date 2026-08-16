"""Validated Pi-to-laptop mode control heartbeat."""

from dataclasses import dataclass
import ipaddress
import json
import time
from typing import Optional


@dataclass(frozen=True)
class ControlState:
    mode: str
    active_panel_id: int
    sequence: int
    received_monotonic_s: float


class ControlReceiver:
    """Accept monotonic control packets only from the configured Pi source."""

    def __init__(
        self,
        socket,
        *,
        allowed_source_id: str,
        allowed_remote_ip: str,
        timeout_s: float,
    ) -> None:
        if not allowed_source_id or not allowed_remote_ip or timeout_s <= 0.0:
            raise ValueError('control receiver configuration is invalid')
        self.socket = socket
        self.allowed_source_id = allowed_source_id
        self.allowed_remote_ip = str(ipaddress.ip_address(allowed_remote_ip))
        self.timeout_s = timeout_s
        self._last: Optional[ControlState] = None

    def poll(self) -> None:
        while True:
            try:
                raw, address = self.socket.recvfrom(4096)
            except BlockingIOError:
                return
            try:
                if str(ipaddress.ip_address(address[0])) != self.allowed_remote_ip:
                    continue
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    continue
                if payload.get('protocol_version') != 1:
                    continue
                if payload.get('source_id') != self.allowed_source_id:
                    continue
                mode = payload.get('mode')
                if mode not in {'idle', 'survey', 'clean'}:
                    continue
                sequence = payload.get('sequence')
                panel_id = payload.get('active_panel_id')
                if isinstance(sequence, bool) or not isinstance(sequence, int):
                    continue
                if isinstance(panel_id, bool) or not isinstance(panel_id, int):
                    continue
                if self._last is not None and sequence <= self._last.sequence:
                    continue
                self._last = ControlState(
                    mode,
                    panel_id,
                    sequence,
                    time.monotonic(),
                )
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue

    def state(self) -> ControlState:
        """Return idle whenever the Pi heartbeat is absent or stale."""
        now_s = time.monotonic()
        if (
            self._last is None
            or now_s - self._last.received_monotonic_s > self.timeout_s
        ):
            return ControlState('idle', -1, 0, now_s)
        return self._last
