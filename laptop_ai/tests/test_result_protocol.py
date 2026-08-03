import json

from laptop_ai.detection_types import DetectionResult
from laptop_ai.result_protocol import deserialize_result, serialize_result


def make_wire_result(frame_id: int = 1) -> DetectionResult:
    result = DetectionResult.from_pixel_detection(
        frame_id=frame_id,
        capture_timestamp_ns=100,
        inference_timestamp_ns=200,
        image_width=640,
        image_height=480,
        centroid=(320, 240),
        bbox=(256, 192, 128, 96),
        area=12288,
        confidence=0.91,
        inference_time_ms=38.2,
        model_name="opencv-mvp",
    )
    return result.with_transport(
        source_id="laptop-ai-01",
        session_id="session-a",
        sequence=frame_id,
        send_timestamp_ns=300,
    )


def test_detection_result_json_round_trip() -> None:
    result = make_wire_result()
    packet = serialize_result(result)
    decoded = deserialize_result(packet)
    assert decoded == result
    assert json.loads(packet)["protocol_version"] == 1


def test_no_detection_message_has_complete_zero_detection_fields() -> None:
    result = DetectionResult.no_detection(
        frame_id=2,
        capture_timestamp_ns=100,
        inference_timestamp_ns=150,
        image_width=640,
        image_height=480,
        inference_time_ms=3.0,
        model_name="opencv-mvp",
    ).with_transport(
        source_id="laptop-ai-01",
        session_id="session-a",
        sequence=2,
        send_timestamp_ns=200,
    )
    decoded = deserialize_result(serialize_result(result))
    assert decoded.dirt_found is False
    assert decoded.confidence == 0.0
    assert decoded.bbox_w_norm == 0.0


def test_packet_size_limit_is_enforced() -> None:
    result = make_wire_result()
    try:
        serialize_result(result, max_packet_bytes=10)
    except ValueError as exc:
        assert "limit" in str(exc)
    else:
        raise AssertionError("expected packet size rejection")
