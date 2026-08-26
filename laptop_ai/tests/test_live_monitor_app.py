from types import SimpleNamespace

import numpy as np
import pytest

from laptop_ai.live_monitor_app import (
    LiveInferenceMonitor,
    dirt_component_overlays,
    selected_dirt_overlay,
)
from laptop_ai.panel_detector import PanelRectangle


def dirt_result():
    component = SimpleNamespace(
        component_id=4,
        bbox_x=10,
        bbox_y=20,
        bbox_width=30,
        bbox_height=40,
        centroid_x=25.0,
        centroid_y=40.0,
        confidence=0.91,
    )
    return SimpleNamespace(
        components=(component,),
        centroid_x_norm=0.25,
        centroid_y_norm=0.50,
        bbox_x_norm=0.10,
        bbox_y_norm=0.20,
        bbox_w_norm=0.30,
        bbox_h_norm=0.40,
        confidence=0.91,
        total_dirty_area_ratio=0.08,
        component_count=1,
        target_component_area_ratio=0.08,
    )


def test_all_dirt_components_map_from_panel_roi_to_full_frame():
    panel = PanelRectangle(1, 100, 50, 200, 100, 0.9)
    values = dirt_component_overlays(dirt_result(), panel, 1000, 500)

    assert len(values) == 1
    assert values[0]['component_id'] == 4.0
    assert values[0]['bbox_x_norm'] == pytest.approx(0.11)
    assert values[0]['bbox_y_norm'] == pytest.approx(0.14)
    assert values[0]['bbox_w_norm'] == pytest.approx(0.03)
    assert values[0]['bbox_h_norm'] == pytest.approx(0.08)


def test_selected_dirt_maps_to_full_frame_status_box():
    panel = PanelRectangle(1, 100, 50, 200, 100, 0.9)
    values = selected_dirt_overlay(dirt_result(), panel, 1000, 500)

    assert values['dirt_centroid_x_norm'] == pytest.approx(0.15)
    assert values['dirt_centroid_y_norm'] == pytest.approx(0.20)
    assert values['dirt_bbox_x_norm'] == pytest.approx(0.12)
    assert values['dirt_bbox_y_norm'] == pytest.approx(0.14)
    assert values['dirt_bbox_w_norm'] == pytest.approx(0.06)
    assert values['dirt_bbox_h_norm'] == pytest.approx(0.08)


def test_component_mapping_rejects_invalid_dimensions():
    panel = PanelRectangle(1, 0, 0, 0, 100, 0.9)
    with pytest.raises(ValueError, match='dimensions'):
        dirt_component_overlays(dirt_result(), panel, 1000, 500)


def test_observe_mode_runs_dirt_for_every_panel_on_the_same_frame():
    panels = [
        PanelRectangle(1, 10, 20, 100, 80, 0.9),
        PanelRectangle(2, 180, 90, 80, 60, 0.8),
    ]

    class PanelDetector:
        model_name = 'panel.onnx'

        def detect(self, frame):
            return panels

    class DirtDetector:
        model_name = 'dirt.onnx'

        def __init__(self):
            self.calls = 0

        def detect(self, roi, **_target):
            self.calls += 1
            return dirt_result()

    monitor = LiveInferenceMonitor.__new__(LiveInferenceMonitor)
    monitor.panel_detector = PanelDetector()
    monitor.dirt_detector = DirtDetector()
    monitor.target_x_norm = 0.5
    monitor.target_y_norm = 0.5
    monitor.maximum_target_distance_norm = 1.0
    monitor.frame_id = 7
    monitor.pi_ip = '192.0.2.10'

    found_panels, _selected, state = monitor.analyze_frame(
        np.zeros((240, 320, 3), dtype=np.uint8)
    )

    assert found_panels == panels
    assert monitor.dirt_detector.calls == 2
    assert state.mode == 'observe'
    assert state.dirt_found is True
    assert len(state.dirt_components) == 2
