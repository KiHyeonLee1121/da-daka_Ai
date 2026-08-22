"""Client for the local ROS operator gateway Unix socket."""

import json
import socket
from pathlib import Path


START_CONFIRMATION = 'START AUTONOMOUS CLEANING'
VALIDATION_CONFIRMATION = 'START 1M FLIGHT VALIDATION'


class GatewayError(RuntimeError):
    """Report a local gateway connection or protocol failure."""


class GatewayClient:
    """Send allowlisted commands to the ROS gateway over a Unix socket."""

    def __init__(self, socket_path: Path, timeout_s: float = 1.5) -> None:
        """Store the local socket path and per-request timeout."""
        self.socket_path = Path(socket_path)
        self.timeout_s = float(timeout_s)

    def request(self, command: str, **fields) -> dict:
        """Send one JSON request and return its decoded response."""
        payload = {'command': command, **fields}
        encoded = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout_s)
                sock.connect(str(self.socket_path))
                sock.sendall(encoded + b'\n')
                response = self._receive_line(sock)
        except (FileNotFoundError, ConnectionRefusedError, socket.timeout) as exc:
            raise GatewayError(f'operator gateway unavailable: {exc}') from exc
        except OSError as exc:
            raise GatewayError(f'operator gateway I/O failed: {exc}') from exc
        try:
            result = json.loads(response.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GatewayError('operator gateway returned invalid JSON') from exc
        if not isinstance(result, dict):
            raise GatewayError('operator gateway response is not an object')
        return result

    @staticmethod
    def _receive_line(sock: socket.socket) -> bytes:
        chunks = bytearray()
        while len(chunks) <= 65536:
            block = sock.recv(4096)
            if not block:
                break
            chunks.extend(block)
            newline = chunks.find(b'\n')
            if newline >= 0:
                return bytes(chunks[:newline])
        if len(chunks) > 65536:
            raise GatewayError('operator gateway response is too large')
        raise GatewayError('operator gateway closed without a response')

    def status(self) -> dict:
        """Return the latest aggregate flight and mission status."""
        response = self.request('status')
        if not response.get('ok') or not isinstance(response.get('status'), dict):
            raise GatewayError(str(response.get('error', 'status request failed')))
        return response['status']

    def start(self) -> dict:
        """Request the complete mission with the required confirmation token."""
        return self.request('start', confirmation=START_CONFIRMATION)

    def abort(self) -> dict:
        """Request mission abort and the mission-owned landing sequence."""
        return self.request('abort')

    def start_validation(self, checklist: list[str]) -> dict:
        """Request the staged 1 m flight validation mission."""
        return self.request(
            'validation_start',
            confirmation=VALIDATION_CONFIRMATION,
            checklist=checklist,
        )

    def abort_validation(self) -> dict:
        """Request validation abort and its safe landing sequence."""
        return self.request('validation_abort')
