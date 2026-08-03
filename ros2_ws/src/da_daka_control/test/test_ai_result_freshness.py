import json

from da_daka_control.ai_result_protocol import (
    FreshnessMonitor,
    PacketProcessor,
    ValidationConfig,
)


def payload(**overrides):
    message = {
        "protocol_version": 1,
        "source_id": "laptop-ai-01",
        "session_id": "session-a",
        "frame_id": 1,
        "capture_timestamp_ns": 100,
        "inference_timestamp_ns": 200,
        "send_timestamp_ns": 300,
        "image_width": 640,
        "image_height": 480,
        "dirt_found": True,
        "centroid_x_norm": 0.5,
        "centroid_y_norm": 0.5,
        "bbox_x_norm": 0.4,
        "bbox_y_norm": 0.4,
        "bbox_w_norm": 0.2,
        "bbox_h_norm": 0.2,
        "area_ratio": 0.04,
        "confidence": 0.9,
        "inference_time_ms": 10.0,
        "model_name": "test",
        "sequence": 1,
    }
    message.update(overrides)
    return message


def accepted_result():
    processor = PacketProcessor(ValidationConfig(allowed_source_id="laptop-ai-01"))
    outcome = processor.process(json.dumps(payload()))
    assert outcome.result is not None
    return outcome.result


def test_result_becomes_stale_before_heartbeat_timeout() -> None:
    monitor = FreshnessMonitor()
    monitor.observe(accepted_result(), receive_monotonic_ns=1_000_000_000)
    state = monitor.snapshot(
        now_monotonic_ns=1_500_000_000,
        max_result_age_s=0.4,
        heartbeat_timeout_s=1.0,
    )
    assert state.healthy
    assert not state.result_valid
    assert state.invalid_reason == "stale_result"


def test_heartbeat_timeout_marks_ai_unhealthy() -> None:
    monitor = FreshnessMonitor()
    monitor.observe(accepted_result(), receive_monotonic_ns=1_000_000_000)
    state = monitor.snapshot(
        now_monotonic_ns=2_100_000_000,
        max_result_age_s=0.4,
        heartbeat_timeout_s=1.0,
    )
    assert not state.healthy
    assert not state.result_valid
    assert state.invalid_reason == "heartbeat_timeout"


def test_sender_wall_clock_age_is_optional_and_can_reject_stale_packet() -> None:
    processor = PacketProcessor(
        ValidationConfig(
            allowed_source_id="laptop-ai-01",
            use_sender_timestamp_for_age=True,
            max_result_age_s=0.4,
        )
    )
    message = payload(send_timestamp_ns=1_000_000_000)
    outcome = processor.process(
        json.dumps(message),
        now_wall_ns=1_500_000_000,
    )
    assert outcome.result is None
    assert outcome.error_code == "stale_result"
