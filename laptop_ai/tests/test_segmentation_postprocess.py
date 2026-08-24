import numpy as np

from laptop_ai.preprocessing import compute_letterbox_transform
from laptop_ai.segmentation_postprocess import (
    ComponentSelectionPolicy,
    connected_components,
    postprocess_segmentation,
    select_target_component,
)


def test_single_component_centroid_and_total_ratio():
    probability = np.zeros((100, 200), dtype=np.float32)
    probability[20:40, 50:90] = 0.9
    mask, components = connected_components(
        probability,
        threshold=0.5,
        minimum_component_area=1,
        minimum_component_area_ratio=0.0,
    )
    assert len(components) == 1
    component = components[0]
    assert component.area == 800
    assert component.centroid_x == 69.5
    assert component.centroid_y == 29.5
    assert np.count_nonzero(mask) == 800


def test_separated_components_do_not_create_empty_middle_centroid():
    probability = np.zeros((100, 200), dtype=np.float32)
    probability[20:30, 10:20] = 0.8
    probability[60:80, 160:190] = 0.95
    _mask, components = connected_components(
        probability,
        threshold=0.5,
        minimum_component_area=1,
        minimum_component_area_ratio=0.0,
    )
    assert len(components) == 2
    target = select_target_component(
        components,
        image_width=200,
        image_height=100,
        target_x_norm=0.9,
        target_y_norm=0.7,
        policy=ComponentSelectionPolicy(0.2, 0.2, 0.6),
    )
    assert target.centroid_x > 150


def test_component_noise_is_filtered_individually():
    probability = np.zeros((50, 50), dtype=np.float32)
    probability[1, 1] = 0.99
    probability[4, 4] = 0.99
    probability[20:25, 20:25] = 0.8
    _mask, components = connected_components(
        probability,
        threshold=0.5,
        minimum_component_area=4,
        minimum_component_area_ratio=0.0,
    )
    assert len(components) == 1
    assert components[0].area == 25


def test_postprocess_uses_explicit_logits_and_original_roi_coordinates():
    transform = compute_letterbox_transform(200, 100, 200, 200)
    logits = np.full((1, 1, 200, 200), -10.0, dtype=np.float32)
    logits[0, 0, 70:90, 50:90] = 10.0
    result = postprocess_segmentation(
        logits,
        transform,
        activation='logits',
        output_layout='NCHW',
        output_channel=0,
        threshold=0.5,
        minimum_component_area=1,
        minimum_component_area_ratio=0.0,
    )
    assert result.component_count == 1
    assert result.target is not None
    assert result.target.bbox_y <= 20
    assert result.total_dirty_area_ratio == result.target.area_ratio
