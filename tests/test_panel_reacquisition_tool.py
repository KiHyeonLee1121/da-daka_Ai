"""Tests for the panel reacquisition field-test image helpers."""

import importlib.util
from pathlib import Path
import sys

import cv2
import numpy as np
import pytest


def _load_tool_module():
    path = Path(__file__).parents[1] / 'tools' / 'panel_reacquisition_test.py'
    spec = importlib.util.spec_from_file_location(
        'panel_reacquisition_test_tool',
        path,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


TOOL = _load_tool_module()


def test_installed_camera_frame_is_rotated_180_degrees():
    """The saved frame must match the physical DA-DAKA camera mounting."""
    frame = np.array([[1, 2], [3, 4]], dtype=np.uint8)
    result = TOOL.orient_da_daka_camera_frame(frame)
    assert result.tolist() == [[4, 3], [2, 1]]


def test_camera_yaw_default_does_not_double_apply_rotation():
    """No additional yaw offset is needed after rotating the image."""
    args = TOOL.build_parser().parse_args([])
    assert args.camera_yaw_offset_deg == 0.0


def test_blue_panel_fallback_rejects_edge_connected_court():
    """A small isolated blue panel wins over blue areas touching an edge."""
    frame = np.full((1080, 1920, 3), 180, dtype=np.uint8)
    cv2.rectangle(frame, (1500, 0), (1919, 1079), (160, 80, 20), -1)
    cv2.rectangle(frame, (420, 700), (620, 830), (160, 80, 20), -1)

    candidates = TOOL.detect_panel_candidates(
        frame,
        min_area_ratio=0.015,
        max_area_ratio=0.90,
    )

    assert len(candidates) == 1
    assert candidates[0].center_x == pytest.approx(520.0, abs=2.0)
    assert candidates[0].center_y == pytest.approx(765.0, abs=2.0)
