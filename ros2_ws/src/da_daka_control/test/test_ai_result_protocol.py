import json

import pytest

from da_daka_control.ai_result_protocol import (
    PacketProcessor,
    ValidationConfig,
)


def payload(**overrides):
    base = {
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
    base.update(overrides)
    return base


@pytest.fixture
def processor():
    return PacketProcessor(ValidationConfig(allowed_source_id="laptop-ai-01"))


def process(processor, **overrides):
    return processor.process(json.dumps(payload(**overrides)))


def test_normal_json_is_accepted(processor) -> None:
    outcome = process(processor)
    assert outcome.result is not None
    assert outcome.result.valid


def test_complete_no_detection_heartbeat_is_accepted(processor) -> None:
    outcome = process(
        processor,
        dirt_found=False,
        centroid_x_norm=0.0,
        centroid_y_norm=0.0,
        bbox_x_norm=0.0,
        bbox_y_norm=0.0,
        bbox_w_norm=0.0,
        bbox_h_norm=0.0,
        area_ratio=0.0,
        confidence=0.0,
    )
    assert outcome.result is not None
    assert not outcome.result.dirt_found
    assert outcome.result.valid


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"protocol_version": 2}, "protocol_version"),
        ({"confidence": 1.1}, "normalized_range"),
        ({"centroid_x_norm": -0.1}, "normalized_range"),
        ({"bbox_x_norm": 0.9, "bbox_w_norm": 0.2}, "bbox_range"),
        ({"source_id": "intruder"}, "source_id"),
        ({"confidence": float("nan")}, "non_finite"),
    ],
)
def test_invalid_values_are_rejected(processor, overrides, code) -> None:
    outcome = process(processor, **overrides)
    assert outcome.result is None
    assert outcome.error_code == code


def test_missing_required_field_is_rejected(processor) -> None:
    message = payload()
    del message["session_id"]
    outcome = processor.process(json.dumps(message))
    assert outcome.error_code == "missing_fields"


def test_duplicate_and_past_sequence_are_rejected(processor) -> None:
    assert process(processor).result is not None
    assert process(processor, frame_id=2, sequence=1).error_code == "duplicate_sequence"
    assert process(processor, frame_id=2, sequence=0).error_code == "past_sequence"


def test_duplicate_and_past_frame_are_rejected(processor) -> None:
    assert process(processor, frame_id=10, sequence=10).result is not None
    assert process(processor, frame_id=10, sequence=11).error_code == "duplicate_frame"
    assert process(processor, frame_id=9, sequence=12).error_code == "past_frame"


def test_new_session_resets_sequence_baseline(processor) -> None:
    assert process(processor, frame_id=10, sequence=10).result is not None
    outcome = process(
        processor,
        session_id="session-b",
        frame_id=1,
        sequence=1,
    )
    assert outcome.result is not None


def test_low_confidence_detection_is_received_but_invalid(processor) -> None:
    outcome = process(processor, confidence=0.4)
    assert outcome.result is not None
    assert not outcome.result.valid
    assert outcome.result.invalid_reason == "below_minimum_confidence"


def test_slow_inference_is_received_but_invalid(processor) -> None:
    outcome = process(processor, inference_time_ms=500.0)
    assert outcome.result is not None
    assert not outcome.result.valid
    assert outcome.result.invalid_reason == "inference_too_slow"


def test_malformed_packet_does_not_poison_next_valid_packet(processor) -> None:
    malformed = processor.process(b"{not-json")
    accepted = process(processor)
    assert malformed.error_code == "invalid_json"
    assert accepted.result is not None
    assert processor.counters.malformed == 1
    assert processor.counters.accepted == 1
