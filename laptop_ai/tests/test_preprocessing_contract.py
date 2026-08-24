import numpy as np

from laptop_ai.preprocessing import (
    compute_letterbox_transform,
    inverse_letterbox_map,
    letterbox_image,
)


def test_letterbox_preserves_aspect_ratio_and_padding():
    image = np.zeros((350, 1000, 3), dtype=np.uint8)
    output, transform = letterbox_image(image, 512, 512)
    assert output.shape == (512, 512, 3)
    assert transform.resized_width == 512
    assert transform.resized_height == 179
    assert transform.pad_left == 0
    assert transform.pad_top + transform.resized_height + transform.pad_bottom == 512
    assert abs(
        transform.resized_width / transform.resized_height - 1000 / 350
    ) < 0.01


def test_bbox_round_trip_is_invertible():
    transform = compute_letterbox_transform(1000, 350, 640, 384)
    original = (123.5, 42.0, 456.0, 210.0)
    restored = transform.to_original_bbox(transform.to_input_bbox(original))
    assert np.allclose(restored, original, atol=1e-4)


def test_mask_coordinate_round_trip_removes_padding():
    mask = np.zeros((350, 1000), dtype=np.uint8)
    mask[80:220, 300:700] = 1
    padded, transform = letterbox_image(
        mask,
        512,
        512,
        padding_value=0,
        interpolation=0,
    )
    restored = inverse_letterbox_map(padded, transform, interpolation=0) > 0
    truth = mask > 0
    intersection = np.count_nonzero(restored & truth)
    union = np.count_nonzero(restored | truth)
    assert intersection / union > 0.975
