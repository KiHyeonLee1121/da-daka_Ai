"""Tests for the Pi host edge GPU link launcher."""

import argparse
import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / 'tools' / 'edge_gpu_link.py'
SPEC = importlib.util.spec_from_file_location('edge_gpu_link', MODULE_PATH)
edge_gpu_link = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(edge_gpu_link)


def arguments(**overrides):
    """Build a minimal launcher argument namespace."""
    values = {
        'laptop_ip': '192.0.2.10',
        'video_port': 5600,
        'result_port': 5005,
        'camera_executable': '/usr/bin/rpicam-vid',
        'width': 1280,
        'height': 720,
        'framerate': 20,
        'bitrate': 4_000_000,
        'container_name': 'da-daka-test-link',
        'ros_domain_id': 0,
        'image': edge_gpu_link.DEFAULT_IMAGE,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_camera_command_is_argument_only_mpegts_udp():
    """The camera process must stream MPEG-TS without a shell."""
    command = edge_gpu_link.camera_command(arguments())

    assert command[0] == '/usr/bin/rpicam-vid'
    assert command[command.index('--codec') + 1] == 'libav'
    assert command[command.index('--libav-format') + 1] == 'mpegts'
    assert command[-1] == 'udp://192.0.2.10:5600?pkt_size=1316'


def test_docker_bridge_contains_only_ai_network_nodes(tmp_path):
    """The diagnostic bridge must not start hardware or flight nodes."""
    command = edge_gpu_link.docker_command(arguments(), tmp_path)
    script = command[-1]

    assert '--network' in command
    assert command[command.index('--network') + 1] == 'host'
    assert f'{tmp_path}:/workspace:ro' in command
    assert 'perception_receiver' in script
    assert 'perception_control_sender' in script
    assert 'autonomous_cleaning_mission' not in script
    assert 'mavros' not in script.lower()
    assert 'tf_luna' not in script
    assert 'spray' not in script


@pytest.mark.parametrize(
    'value',
    ['127.0.0.1', '0.0.0.0', '224.0.0.1', 'not-an-address', '::1'],
)
def test_laptop_ip_rejects_non_lan_destinations(value):
    """Unsafe or unsupported destination addresses must fail parsing."""
    with pytest.raises(argparse.ArgumentTypeError):
        edge_gpu_link.laptop_ipv4(value)


def test_laptop_ip_accepts_unicast_ipv4():
    """A field-LAN unicast IPv4 address must be accepted."""
    assert edge_gpu_link.laptop_ipv4('172.29.215.126') == '172.29.215.126'
