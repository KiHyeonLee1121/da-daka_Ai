"""Tests for fail-closed Pi control-heartbeat reception."""

import json

from laptop_ai.control_protocol import ControlReceiver


class FakeSocket:
    """Return queued UDP datagrams without opening a network socket."""

    def __init__(self, packets):
        self.packets = list(packets)

    def recvfrom(self, _maximum_bytes):
        if not self.packets:
            raise BlockingIOError
        return self.packets.pop(0)


def packet(sequence=1):
    """Build one valid Pi control packet."""
    return json.dumps(
        {
            'protocol_version': 1,
            'source_id': 'pi5-01',
            'mode': 'clean',
            'active_panel_id': 7,
            'sequence': sequence,
        }
    ).encode('utf-8')


def receiver(packets):
    """Build a receiver constrained to the field Pi address."""
    return ControlReceiver(
        FakeSocket(packets),
        allowed_source_id='pi5-01',
        allowed_remote_ip='192.168.1.20',
        timeout_s=1.0,
    )


def test_control_receiver_rejects_spoofed_remote_ip():
    control = receiver([(packet(), ('192.168.1.99', 5006))])
    control.poll()
    assert control.state().mode == 'idle'


def test_control_receiver_accepts_matching_id_and_remote_ip():
    control = receiver([(packet(), ('192.168.1.20', 5006))])
    control.poll()
    assert control.state().mode == 'clean'
    assert control.state().active_panel_id == 7


def test_control_receiver_rejects_non_object_json():
    control = receiver([(b'[]', ('192.168.1.20', 5006))])
    control.poll()
    assert control.state().mode == 'idle'
