import socket

import pytest

from laptop_ai.detection_types import DetectionResult
from laptop_ai.result_protocol import deserialize_result
from laptop_ai.udp_result_sender import UdpResultSender


def no_detection(frame_id: int) -> DetectionResult:
    return DetectionResult.no_detection(
        frame_id=frame_id,
        capture_timestamp_ns=100,
        inference_timestamp_ns=200,
        image_width=640,
        image_height=480,
        inference_time_ms=1.0,
        model_name="test",
    )


def test_udp_loopback_and_increasing_sequence() -> None:
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(1.0)
    sender = UdpResultSender(
        "127.0.0.1",
        receiver.getsockname()[1],
        "laptop-ai-01",
        session_id="session-a",
    )
    try:
        sender.send(no_detection(1))
        first = deserialize_result(receiver.recvfrom(4096)[0])
        sender.send(no_detection(2))
        second = deserialize_result(receiver.recvfrom(4096)[0])
        assert (first.sequence, second.sequence) == (1, 2)
        assert first.session_id == second.session_id == "session-a"
    finally:
        sender.close()
        receiver.close()


def test_duplicate_frame_is_not_sent_twice() -> None:
    sender = UdpResultSender("127.0.0.1", 9, "test", session_id="session-a")
    try:
        sender.send(no_detection(1))
        with pytest.raises(ValueError, match="already sent"):
            sender.send(no_detection(1))
    finally:
        sender.close()
