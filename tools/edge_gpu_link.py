#!/usr/bin/env python3
"""Run the Pi camera and ROS edge-GPU network bridge without flight nodes."""

from __future__ import annotations

import argparse
import ipaddress
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path


DEFAULT_IMAGE = 'local/ros2-jazzy-mavros:latest'
DEFAULT_CONTAINER = 'da-daka-edge-gpu-link'


def laptop_ipv4(value: str) -> str:
    """Return a safe unicast IPv4 address for the field laptop."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if address.version != 4:
        raise argparse.ArgumentTypeError(
            'the current video command requires IPv4'
        )
    if address.is_unspecified or address.is_multicast or address.is_loopback:
        raise argparse.ArgumentTypeError(
            'laptop IP must be a LAN unicast address'
        )
    return str(address)


def positive_int(value: str) -> int:
    """Parse a positive integer CLI argument."""
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError('value must be positive')
    return parsed


def nonnegative_float(value: str) -> float:
    """Parse a non-negative duration."""
    parsed = float(value)
    if parsed < 0.0:
        raise argparse.ArgumentTypeError('duration cannot be negative')
    return parsed


def camera_command(args: argparse.Namespace) -> list[str]:
    """Build the argument-only rpicam MPEG-TS/UDP command."""
    output = f'udp://{args.laptop_ip}:{args.video_port}?pkt_size=1316'
    return [
        args.camera_executable,
        '-t',
        '0',
        '-n',
        '--codec',
        'libav',
        '--libav-format',
        'mpegts',
        '--low-latency',
        '--width',
        str(args.width),
        '--height',
        str(args.height),
        '--framerate',
        str(args.framerate),
        '--bitrate',
        str(args.bitrate),
        '-o',
        output,
    ]


def docker_command(args: argparse.Namespace, workspace: Path) -> list[str]:
    """Build the network-only ROS container command."""
    bridge = r"""
set -e
source /opt/ros/jazzy/setup.bash
source /workspace/install/setup.bash
receiver_pid=
sender_pid=
cleanup() {
  trap - TERM INT EXIT
  test -z "$receiver_pid" || kill -TERM "$receiver_pid" 2>/dev/null || true
  test -z "$sender_pid" || kill -TERM "$sender_pid" 2>/dev/null || true
  test -z "$receiver_pid" || wait "$receiver_pid" 2>/dev/null || true
  test -z "$sender_pid" || wait "$sender_pid" 2>/dev/null || true
}
trap cleanup TERM INT EXIT
ros2 run da_daka_control perception_receiver --ros-args \
  -p allowed_remote_ip:="$LAPTOP_IP" &
receiver_pid=$!
ros2 run da_daka_control perception_control_sender --ros-args \
  -p laptop_ip:="$LAPTOP_IP" &
sender_pid=$!
wait -n "$receiver_pid" "$sender_pid"
""".strip()
    return [
        'docker',
        'run',
        '--rm',
        '--name',
        args.container_name,
        '--network',
        'host',
        '--ipc',
        'host',
        '-e',
        f'ROS_DOMAIN_ID={args.ros_domain_id}',
        '-e',
        'RMW_IMPLEMENTATION=rmw_cyclonedds_cpp',
        '-e',
        f'LAPTOP_IP={args.laptop_ip}',
        '-v',
        f'{workspace}:/workspace:ro',
        '--entrypoint',
        'bash',
        args.image,
        '-lc',
        bridge,
    ]


def _check_udp_port_available(port: int) -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind(('0.0.0.0', port))
    except OSError as exc:
        raise RuntimeError(f'UDP {port} is already in use: {exc}') from exc
    finally:
        probe.close()


def _camera_is_running(executable: str) -> bool:
    expected = Path(executable).name
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            raw = (proc / 'cmdline').read_bytes()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        command = raw.split(b'\0', 1)[0]
        if command and Path(command.decode(errors='replace')).name == expected:
            return True
    return False


def preflight(args: argparse.Namespace) -> Path:
    """Validate all local resources without starting the stream."""
    workspace = Path(args.workspace).expanduser().resolve()
    setup = workspace / 'install' / 'setup.bash'
    if not setup.is_file():
        raise RuntimeError(f'ROS workspace overlay is missing: {setup}')
    camera = shutil.which(args.camera_executable)
    if camera is None:
        raise RuntimeError(
            f'camera executable not found: {args.camera_executable}'
        )
    args.camera_executable = camera
    if shutil.which('docker') is None:
        raise RuntimeError('docker executable not found')
    if _camera_is_running(camera):
        raise RuntimeError(
            'another rpicam-vid process already owns the camera'
        )
    _check_udp_port_available(args.result_port)
    image = subprocess.run(
        ['docker', 'image', 'inspect', args.image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if image.returncode != 0:
        raise RuntimeError(f'Docker image is unavailable: {args.image}')
    container = subprocess.run(
        ['docker', 'container', 'inspect', args.container_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if container.returncode == 0:
        raise RuntimeError(
            f'container name is already present: {args.container_name}'
        )
    cameras = subprocess.run(
        [camera, '--list-cameras'],
        text=True,
        capture_output=True,
        check=False,
    )
    listing = f'{cameras.stdout}\n{cameras.stderr}'
    if cameras.returncode != 0 or 'Available cameras' not in listing:
        raise RuntimeError('rpicam-vid did not report an available camera')
    return workspace


def _container_running(name: str) -> bool:
    state = subprocess.run(
        ['docker', 'inspect', '-f', '{{.State.Running}}', name],
        text=True,
        capture_output=True,
        check=False,
    )
    return state.returncode == 0 and state.stdout.strip() == 'true'


def _stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3.0)


def run(args: argparse.Namespace) -> int:
    """Run and supervise the camera and network-only ROS bridge."""
    workspace = preflight(args)
    print(f'Pi camera -> {args.laptop_ip}:{args.video_port}/udp')
    print(f'Laptop results -> 0.0.0.0:{args.result_port}/udp')
    print('Flight, MAVROS, LiDAR and spray nodes are not started.')
    if args.preflight_only:
        print('Preflight passed.')
        return 0

    docker_process: subprocess.Popen | None = None
    camera_process: subprocess.Popen | None = None
    started = time.monotonic()
    try:
        docker_process = subprocess.Popen(docker_command(args, workspace))
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if docker_process.poll() is not None:
                raise RuntimeError(
                    'ROS bridge container exited with '
                    f'{docker_process.returncode}'
                )
            if _container_running(args.container_name):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError('ROS bridge container did not become ready')

        camera_process = subprocess.Popen(camera_command(args))
        while True:
            camera_status = camera_process.poll()
            docker_status = docker_process.poll()
            if camera_status is not None:
                raise RuntimeError(f'rpicam-vid exited with {camera_status}')
            if docker_status is not None:
                raise RuntimeError(f'ROS bridge exited with {docker_status}')
            if args.duration and time.monotonic() - started >= args.duration:
                print(f'Completed {args.duration:.1f}s diagnostic run.')
                return 0
            time.sleep(0.2)
    except KeyboardInterrupt:
        print('Stopping edge GPU link.')
        return 0
    finally:
        _stop_process(camera_process)
        if _container_running(args.container_name):
            subprocess.run(
                ['docker', 'stop', '-t', '5', args.container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        _stop_process(docker_process)


def parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    repository = Path(__file__).resolve().parents[1]
    result = argparse.ArgumentParser(
        description=(
            'Stream the Pi camera to a laptop and run only the ROS AI '
            'receiver/control heartbeat nodes.'
        )
    )
    result.add_argument('--laptop-ip', required=True, type=laptop_ipv4)
    result.add_argument('--workspace', default=str(repository / 'ros2_ws'))
    result.add_argument('--image', default=DEFAULT_IMAGE)
    result.add_argument('--container-name', default=DEFAULT_CONTAINER)
    result.add_argument('--camera-executable', default='rpicam-vid')
    result.add_argument('--video-port', type=positive_int, default=5600)
    result.add_argument('--result-port', type=positive_int, default=5005)
    result.add_argument('--width', type=positive_int, default=1280)
    result.add_argument('--height', type=positive_int, default=720)
    result.add_argument('--framerate', type=positive_int, default=20)
    result.add_argument('--bitrate', type=positive_int, default=4_000_000)
    result.add_argument('--ros-domain-id', type=int, default=0)
    result.add_argument('--duration', type=nonnegative_float, default=0.0)
    result.add_argument('--preflight-only', action='store_true')
    return result


def main() -> int:
    """CLI entry point."""
    args = parser().parse_args()
    try:
        return run(args)
    except RuntimeError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
