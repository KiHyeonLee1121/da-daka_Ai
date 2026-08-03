"""UDP sender that owns session and strictly increasing sequence state."""

from __future__ import annotations

from datetime import datetime, timezone
import socket
import threading
import time

from laptop_ai.detection_types import DetectionResult
from laptop_ai.result_protocol import serialize_result


class UdpResultSender:
    def __init__(
        self,
        destination_host: str,
        destination_port: int,
        source_id: str,
        *,
        max_packet_bytes: int = 4096,
        socket_factory=socket.socket,
        session_id: str | None = None,
    ) -> None:
        self.destination = (destination_host, destination_port)
        self.source_id = source_id
        self.max_packet_bytes = max_packet_bytes
        self.session_id = session_id or datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%S.%fZ"
        )
        self._socket = socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        self._sequence = 0
        self._last_frame_id: int | None = None
        self._lock = threading.Lock()

    @property
    def sequence(self) -> int:
        return self._sequence

    def send(self, result: DetectionResult) -> DetectionResult:
        """Send exactly one packet for a new frame and return its wire result."""
        with self._lock:
            if result.frame_id == self._last_frame_id:
                raise ValueError(f"frame {result.frame_id} was already sent")
            self._sequence += 1
            wire_result = result.with_transport(
                source_id=self.source_id,
                session_id=self.session_id,
                sequence=self._sequence,
                send_timestamp_ns=time.time_ns(),
            )
            packet = serialize_result(
                wire_result,
                max_packet_bytes=self.max_packet_bytes,
            )
            sent = self._socket.sendto(packet, self.destination)
            if sent != len(packet):
                raise OSError(f"partial UDP send: {sent}/{len(packet)} bytes")
            self._last_frame_id = result.frame_id
            return wire_result

    def close(self) -> None:
        self._socket.close()
