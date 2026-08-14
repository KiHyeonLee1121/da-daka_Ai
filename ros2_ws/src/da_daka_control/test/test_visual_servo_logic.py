from da_daka_control.visual_servo_node import compute_visual_velocity


def _compute(x: float, y: float):
    return compute_visual_velocity(
        centroid_x_norm=x,
        centroid_y_norm=y,
        horizontal_deadband_norm=0.04,
        vertical_deadband_norm=0.04,
        kp_horizontal=0.35,
        kp_vertical=0.35,
        max_horizontal_speed_mps=0.12,
        max_vertical_image_speed_mps=0.12,
        invert_horizontal=False,
        invert_vertical=True,
    )


def test_centered_target_produces_zero_velocity_and_aligned() -> None:
    horizontal, vertical, aligned = _compute(0.5, 0.5)
    assert horizontal == 0.0
    assert vertical == 0.0
    assert aligned


def test_right_target_requests_positive_horizontal_correction() -> None:
    horizontal, vertical, aligned = _compute(0.8, 0.5)
    assert horizontal > 0.0
    assert vertical == 0.0
    assert not aligned
    assert horizontal <= 0.12


def test_vertical_mapping_uses_configured_inversion() -> None:
    horizontal, vertical, aligned = _compute(0.5, 0.8)
    assert horizontal == 0.0
    assert vertical < 0.0
    assert not aligned
    assert abs(vertical) <= 0.12 + 1e-9
