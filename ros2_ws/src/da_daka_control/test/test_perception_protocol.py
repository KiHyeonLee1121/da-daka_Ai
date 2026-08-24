"""Tests for the laptop-to-Pi perception protocol."""

import json

from da_daka_control.perception_protocol import (
    decode_perception_packet,
    PerceptionProtocolError,
    ProtocolConfig,
    SequenceTracker,
)
import pytest


def packet(**updates):
    payload = {
        'protocol_version': 3,
        'source_id': 'laptop-ai-01',
        'session_id': 'test-session',
        'frame_id': 1,
        'sequence': 1,
        'capture_timestamp_ns': 100,
        'inference_timestamp_ns': 110,
        'send_timestamp_ns': 120,
        'mode': 'survey',
        'image_width': 1280,
        'image_height': 720,
        'valid': True,
        'panel_visible': True,
        'target_panel_selected': False,
        'target_panel_candidate_id': -1,
        'panels': [
            {
                'candidate_id': 1,
                'center_x_norm': 0.5,
                'center_y_norm': 0.5,
                'width_norm': 0.4,
                'height_norm': 0.3,
                'confidence': 0.9,
            }
        ],
        'active_panel_id': -1,
        'dirt_found': False,
        'dirt_centroid_x_norm': 0.0,
        'dirt_centroid_y_norm': 0.0,
        'dirt_bbox_x_norm': 0.0,
        'dirt_bbox_y_norm': 0.0,
        'dirt_bbox_w_norm': 0.0,
        'dirt_bbox_h_norm': 0.0,
        'dirt_confidence': 0.0,
        'total_dirty_area_ratio': 0.0,
        'dirt_component_count': 0,
        'target_component_area_ratio': 0.0,
        'inference_time_ms': 12.0,
        'invalid_reason': '',
        'model_name': 'test-model',
        'model_sha256': '0' * 64,
        'dataset_version': 'test-v1',
    }
    payload.update(updates)
    return json.dumps(payload)


def test_valid_survey_packet_is_decoded():
    result = decode_perception_packet(
        packet(), ProtocolConfig('laptop-ai-01')
    )
    assert result.mode == 'survey'
    assert len(result.panels) == 1
    assert not result.dirt_found


def test_source_allowlist_is_enforced():
    with pytest.raises(PerceptionProtocolError) as error:
        decode_perception_packet(packet(source_id='attacker'), ProtocolConfig('laptop-ai-01'))
    assert error.value.code == 'source_id'


def test_clean_packet_cannot_carry_nonzero_dirt_coordinates():
    with pytest.raises(PerceptionProtocolError) as error:
        decode_perception_packet(
            packet(dirt_centroid_x_norm=0.2), ProtocolConfig('laptop-ai-01')
        )
    assert error.value.code == 'dirt_detection'


def test_sequence_tracker_rejects_duplicate_result():
    config = ProtocolConfig('laptop-ai-01')
    result = decode_perception_packet(packet(), config)
    tracker = SequenceTracker()
    tracker.accept(result)
    with pytest.raises(PerceptionProtocolError) as error:
        tracker.accept(result)
    assert error.value.code == 'sequence_order'


def test_sequence_tracker_rejects_out_of_order_frame():
    config = ProtocolConfig('laptop-ai-01')
    tracker = SequenceTracker()
    tracker.accept(decode_perception_packet(packet(), config))
    newer_sequence_older_frame = decode_perception_packet(
        packet(sequence=2, frame_id=0), config
    )
    with pytest.raises(PerceptionProtocolError) as error:
        tracker.accept(newer_sequence_older_frame)
    assert error.value.code == 'frame_order'


def test_panel_candidate_can_exist_without_selected_target():
    result = decode_perception_packet(
        packet(
            mode='clean',
            active_panel_id=7,
            valid=False,
            panel_visible=True,
            target_panel_selected=False,
            invalid_reason='panel-not-centered',
        ),
        ProtocolConfig('laptop-ai-01'),
    )
    assert result.panel_visible
    assert not result.target_panel_selected
    assert not result.valid


def test_valid_clean_result_keeps_selected_panel_without_dirt():
    result = decode_perception_packet(
        packet(
            mode='clean',
            active_panel_id=7,
            target_panel_selected=True,
            target_panel_candidate_id=1,
        ),
        ProtocolConfig('laptop-ai-01'),
    )
    assert result.valid
    assert result.target_panel_selected
    assert result.target_panel_candidate_id == 1
    assert not result.dirt_found


def test_dirty_component_information_is_validated():
    result = decode_perception_packet(
        packet(
            mode='clean',
            active_panel_id=7,
            valid=True,
            target_panel_selected=True,
            target_panel_candidate_id=1,
            dirt_found=True,
            dirt_centroid_x_norm=0.5,
            dirt_centroid_y_norm=0.5,
            dirt_bbox_x_norm=0.4,
            dirt_bbox_y_norm=0.4,
            dirt_bbox_w_norm=0.2,
            dirt_bbox_h_norm=0.2,
            dirt_confidence=0.9,
            total_dirty_area_ratio=0.08,
            dirt_component_count=2,
            target_component_area_ratio=0.05,
        ),
        ProtocolConfig('laptop-ai-01'),
    )
    assert result.dirt_component_count == 2
    assert result.total_dirty_area_ratio == pytest.approx(0.08)


def test_selected_panel_id_must_reference_a_candidate():
    with pytest.raises(PerceptionProtocolError) as error:
        decode_perception_packet(
            packet(
                mode='clean',
                active_panel_id=7,
                target_panel_selected=True,
                target_panel_candidate_id=99,
            ),
            ProtocolConfig('laptop-ai-01'),
        )
    assert error.value.code == 'panel_selection'


def test_protocol_version_mismatch_fails_closed():
    with pytest.raises(PerceptionProtocolError) as error:
        decode_perception_packet(
            packet(protocol_version=2),
            ProtocolConfig('laptop-ai-01'),
        )
    assert error.value.code == 'protocol_version'


def test_validity_and_reason_must_agree():
    with pytest.raises(PerceptionProtocolError) as error:
        decode_perception_packet(
            packet(valid=False, invalid_reason=''),
            ProtocolConfig('laptop-ai-01'),
        )
    assert error.value.code == 'validity'
