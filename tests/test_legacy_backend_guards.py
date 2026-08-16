"""Ensure superseded hardware paths cannot masquerade as live backends."""

import pytest

from actuator.spray_command import create_spray_controller
from vision.hailo_dirt_detector import HailoDirtDetector


def test_legacy_gpio_spray_fails_closed():
    with pytest.raises(RuntimeError, match='Legacy Python GPIO spray is blocked'):
        create_spray_controller({'backend': 'gpio'}, None)


def test_unavailable_hailo_backend_fails_closed():
    with pytest.raises(RuntimeError, match='CUDA ONNX laptop worker'):
        HailoDirtDetector({'model_path': 'unused.hef'})
