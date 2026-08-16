#!/usr/bin/env python3
"""Offline metric check for one 3 m survey observation; never controls flight."""

import argparse
import json
from pathlib import Path
import sys


PACKAGE_ROOT = (
    Path(__file__).resolve().parents[1]
    / 'ros2_ws'
    / 'src'
    / 'da_daka_control'
)
sys.path.insert(0, str(PACKAGE_ROOT))

from da_daka_control.panel_mapping import (  # noqa: E402
    CameraGroundModel,
    PanelObservation,
    project_panel_observation_attitude,
)


def comma_floats(value: str, count: int) -> tuple[float, ...]:
    try:
        result = tuple(float(item) for item in value.split(','))
    except ValueError as exc:
        raise argparse.ArgumentTypeError('expected comma-separated numbers') from exc
    if len(result) != count:
        raise argparse.ArgumentTypeError(f'expected {count} comma-separated numbers')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Project one normalized panel rectangle into local ENU metres'
    )
    parser.add_argument('--panel', required=True, help='center_x,center_y,width,height,confidence')
    parser.add_argument('--pose', required=True, help='east,north,up')
    parser.add_argument('--quaternion', required=True, help='x,y,z,w')
    parser.add_argument('--range-m', type=float, required=True)
    parser.add_argument('--footprint-at-1m', default='1.30,0.73', help='width,height')
    parser.add_argument('--mount-rpy-deg', default='0,0,0', help='roll,pitch,yaw')
    parser.add_argument('--camera-offset', default='0,0,0', help='forward,left,up metres')
    parser.add_argument('--image-x-positive-left', action='store_true')
    parser.add_argument('--image-y-positive-forward', action='store_true')
    args = parser.parse_args()

    panel = comma_floats(args.panel, 5)
    pose = comma_floats(args.pose, 3)
    quaternion = comma_floats(args.quaternion, 4)
    footprint = comma_floats(args.footprint_at_1m, 2)
    mount_degrees = comma_floats(args.mount_rpy_deg, 3)
    offset = comma_floats(args.camera_offset, 3)
    mount_radians = tuple(value * 3.141592653589793 / 180.0 for value in mount_degrees)

    result = project_panel_observation_attitude(
        PanelObservation(*panel),
        CameraGroundModel(
            footprint[0],
            footprint[1],
            args.image_x_positive_left,
            args.image_y_positive_forward,
        ),
        vehicle_east_m=pose[0],
        vehicle_north_m=pose[1],
        vehicle_up_m=pose[2],
        vehicle_quaternion_xyzw=quaternion,
        measured_center_distance_m=args.range_m,
        camera_mount_rpy_rad=mount_radians,
        camera_offset_body_m=offset,
    )
    print(json.dumps({
        'east_m': result.east_m,
        'north_m': result.north_m,
        'width_m': result.width_m,
        'height_m': result.height_m,
        'confidence': result.confidence,
    }, indent=2))


if __name__ == '__main__':
    main()
