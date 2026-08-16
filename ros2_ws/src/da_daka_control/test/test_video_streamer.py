"""Tests for the shell-free Raspberry Pi camera command."""

from da_daka_control.video_streaming import build_rpicam_command
import pytest


def test_command_uses_low_latency_mpegts_udp():
    command = build_rpicam_command(
        executable='rpicam-vid',
        laptop_ip='192.0.2.10',
        port=5600,
        width=1280,
        height=720,
        framerate=20,
        bitrate_bps=4000000,
    )
    assert command[0] == 'rpicam-vid'
    assert '--low-latency' in command
    assert command[command.index('--libav-format') + 1] == 'mpegts'
    assert command[-1] == 'udp://192.0.2.10:5600?pkt_size=1316'


def test_hostname_and_shell_tokens_are_rejected():
    with pytest.raises(ValueError):
        build_rpicam_command(
            executable='rpicam-vid',
            laptop_ip='laptop;shutdown',
            port=5600,
            width=1280,
            height=720,
            framerate=20,
            bitrate_bps=4000000,
        )
