"""Tests for physical camera-to-nozzle image targeting."""

from da_daka_control.nozzle_alignment import (
    compute_image_velocity,
    nozzle_image_target,
)
from da_daka_control.panel_mapping import CameraGroundModel
import pytest


def test_zero_nozzle_offset_targets_image_center():
    target = nozzle_image_target(
        CameraGroundModel(1.0, 1.0),
        camera_to_nozzle_forward_m=0.0,
        camera_to_nozzle_left_m=0.0,
        distance_m=1.0,
    )
    assert target.x_norm == pytest.approx(0.5)
    assert target.y_norm == pytest.approx(0.5)
    assert target.inside_safe_frame


def test_forward_left_nozzle_offset_moves_image_target():
    target = nozzle_image_target(
        CameraGroundModel(2.0, 2.0),
        camera_to_nozzle_forward_m=0.2,
        camera_to_nozzle_left_m=0.1,
        distance_m=1.0,
    )
    assert target.x_norm == pytest.approx(0.45)
    assert target.y_norm == pytest.approx(0.40)


def test_visual_velocity_aligns_to_offset_target_not_frame_center():
    x_speed, y_speed, aligned = compute_image_velocity(
        observed_x_norm=0.45,
        observed_y_norm=0.40,
        target_x_norm=0.45,
        target_y_norm=0.40,
        deadband_norm=0.02,
        gain_mps_per_norm=0.4,
        maximum_speed_mps=0.1,
    )
    assert (x_speed, y_speed) == (0.0, 0.0)
    assert aligned
