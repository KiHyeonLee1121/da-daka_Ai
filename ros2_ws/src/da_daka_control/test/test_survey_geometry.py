import math

import pytest

from da_daka_control.survey_geometry import (
    body_forward_right_to_enu,
    build_panel_target,
    ground_span_from_lidar,
    pixel_to_ground_offset,
)


def test_reference_span_at_three_meters() -> None:
    span = ground_span_from_lidar(3.0)
    assert span.width_m == pytest.approx(3.9)
    assert span.height_m == pytest.approx(2.2)


def test_center_pixel_is_zero_ground_offset() -> None:
    span = ground_span_from_lidar(3.0)
    offset = pixel_to_ground_offset(
        960.0,
        540.0,
        1920,
        1080,
        span,
    )
    assert offset.forward_m == pytest.approx(0.0)
    assert offset.right_m == pytest.approx(0.0)


def test_quarter_width_right_is_about_0_975_m() -> None:
    span = ground_span_from_lidar(3.0)
    offset = pixel_to_ground_offset(
        1440.0,
        540.0,
        1920,
        1080,
        span,
    )
    assert offset.forward_m == pytest.approx(0.0)
    assert offset.right_m == pytest.approx(0.975)


def test_body_right_maps_to_negative_north_at_zero_enu_yaw() -> None:
    east, north = body_forward_right_to_enu(
        forward_m=0.0,
        right_m=1.0,
        yaw_enu_rad=0.0,
    )
    assert east == pytest.approx(0.0)
    assert north == pytest.approx(-1.0)


def test_forward_maps_to_north_at_90_degree_enu_yaw() -> None:
    east, north = body_forward_right_to_enu(
        forward_m=1.0,
        right_m=0.0,
        yaw_enu_rad=math.pi / 2.0,
    )
    assert east == pytest.approx(0.0, abs=1e-9)
    assert north == pytest.approx(1.0)


def test_target_uses_lidar_to_compute_low_altitude_up_coordinate() -> None:
    target = build_panel_target(
        capture_east_m=2.0,
        capture_north_m=3.0,
        capture_up_m=3.24,
        yaw_enu_rad=0.0,
        lidar_distance_m=3.0,
        panel_pixel_x=960.0,
        panel_pixel_y=540.0,
        image_width=1920,
        image_height=1080,
        approach_distance_m=1.0,
    )
    assert target.east_m == pytest.approx(2.0)
    assert target.north_m == pytest.approx(3.0)
    assert target.up_m == pytest.approx(1.24)
