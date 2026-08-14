#!/usr/bin/env python3
"""DA-DAKA high-altitude panel-coordinate/reacquisition field test.

Flow:
3 m downward image -> panel center pixel -> metric MAVROS local ENU target
-> publish target for the control-team program -> after movement, capture a
low-altitude verification image and check whether the panel is in frame.

This file NEVER arms, changes PX4 mode, or sends flight setpoints.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Optional

import cv2
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTROL_PACKAGE_ROOT = REPO_ROOT / 'ros2_ws' / 'src' / 'da_daka_control'
sys.path.insert(0, str(CONTROL_PACKAGE_ROOT))

from da_daka_control.survey_geometry import build_panel_target


@dataclass(frozen=True, slots=True)
class PanelCandidate:
    """Coarse rectangular panel candidate used only for today's test."""

    x: int
    y: int
    w: int
    h: int
    center_x: float
    center_y: float
    score: float


def parse_pair(text: str) -> tuple[float, float]:
    """Parse X,Y."""
    try:
        x_text, y_text = text.split(',', 1)
        return float(x_text), float(y_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('expected numeric X,Y') from exc


def parse_bbox(text: str) -> tuple[int, int, int, int]:
    """Parse X,Y,W,H."""
    parts = text.split(',')
    if len(parts) != 4:
        raise argparse.ArgumentTypeError('expected X,Y,W,H')
    try:
        x, y, w, h = (int(value) for value in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('bbox values must be integers') from exc
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError('bbox width/height must be positive')
    return x, y, w, h


def quaternion_to_rpy(
    x: float,
    y: float,
    z: float,
    w: float,
) -> tuple[float, float, float]:
    """Convert a ROS quaternion to roll, pitch, yaw."""
    roll = math.atan2(
        2.0 * (w * x + y * z),
        1.0 - 2.0 * (x * x + y * y),
    )
    sin_pitch = 2.0 * (w * y - z * x)
    pitch = (
        math.copysign(math.pi / 2.0, sin_pitch)
        if abs(sin_pitch) >= 1.0
        else math.asin(sin_pitch)
    )
    yaw = math.atan2(
        2.0 * (w * z + x * y),
        1.0 - 2.0 * (y * y + z * z),
    )
    return roll, pitch, yaw


def capture_frame(
    *,
    width: int,
    height: int,
    camera_index: int,
    output_path: Path,
) -> np.ndarray:
    """Capture using rpicam-still, Picamera2, or OpenCV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rpicam = shutil.which('rpicam-still')
    if rpicam:
        result = subprocess.run(
            [
                rpicam,
                '--nopreview',
                '--timeout',
                '500',
                '--width',
                str(width),
                '--height',
                str(height),
                '--output',
                str(output_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            frame = cv2.imread(str(output_path), cv2.IMREAD_COLOR)
            if frame is not None:
                return frame

    try:
        from picamera2 import Picamera2

        camera = Picamera2()
        camera.configure(
            camera.create_still_configuration(
                main={'size': (width, height), 'format': 'RGB888'}
            )
        )
        camera.start()
        time.sleep(0.7)
        rgb = camera.capture_array()
        camera.stop()
        camera.close()
        frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        cv2.imwrite(str(output_path), frame)
        return frame
    except (ImportError, RuntimeError):
        pass

    capture = cv2.VideoCapture(camera_index)
    if not capture.isOpened():
        raise RuntimeError(
            'camera unavailable: rpicam-still, Picamera2 and OpenCV failed'
        )
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    frame = None
    for _ in range(8):
        ok, candidate = capture.read()
        if ok:
            frame = candidate
        time.sleep(0.04)
    capture.release()
    if frame is None:
        raise RuntimeError('camera opened but returned no image')
    cv2.imwrite(str(output_path), frame)
    return frame


def detect_panel_candidates(
    frame: np.ndarray,
    *,
    min_area_ratio: float,
    max_area_ratio: float,
) -> list[PanelCandidate]:
    """Find coarse rectangular candidates; not the production panel model."""
    height, width = frame.shape[:2]
    image_area = float(width * height)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 50, 150)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(
        edges,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    candidates: list[PanelCandidate] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        ratio = area / image_area
        if not min_area_ratio <= ratio <= max_area_ratio:
            continue
        perimeter = cv2.arcLength(contour, True)
        if perimeter <= 0.0:
            continue
        polygon = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
        if len(polygon) < 4 or len(polygon) > 8:
            continue
        x, y, w, h = cv2.boundingRect(polygon)
        if w < 20 or h < 20:
            continue
        rectangularity = area / float(w * h)
        aspect = max(w / h, h / w)
        if rectangularity < 0.45 or aspect > 5.0:
            continue
        candidates.append(
            PanelCandidate(
                x=x,
                y=y,
                w=w,
                h=h,
                center_x=x + w / 2.0,
                center_y=y + h / 2.0,
                score=ratio * rectangularity,
            )
        )
    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates[:20]


def choose_center(
    frame: np.ndarray,
    candidates: list[PanelCandidate],
    args: argparse.Namespace,
) -> tuple[float, float, Optional[int]]:
    """Choose a panel center from manual override, GUI ROI, or auto result."""
    height, width = frame.shape[:2]

    if args.center is not None:
        x, y = args.center
        if not 0.0 <= x <= width or not 0.0 <= y <= height:
            raise RuntimeError('--center is outside the image')
        return x, y, None

    if args.bbox is not None:
        x, y, w, h = args.bbox
        return x + w / 2.0, y + h / 2.0, None

    if args.interactive:
        x, y, w, h = (
            int(value)
            for value in cv2.selectROI(
                'Select panel',
                frame,
                showCrosshair=True,
                fromCenter=False,
            )
        )
        cv2.destroyWindow('Select panel')
        if w <= 0 or h <= 0:
            raise RuntimeError('panel ROI selection cancelled')
        return x + w / 2.0, y + h / 2.0, None

    if not candidates:
        raise RuntimeError(
            'no automatic panel rectangle found. Inspect survey.jpg and rerun '
            'with --center X,Y, --bbox X,Y,W,H, or --interactive.'
        )
    if not 0 <= args.panel_index < len(candidates):
        raise RuntimeError(
            f'panel index {args.panel_index} invalid; '
            f'{len(candidates)} candidates found'
        )
    selected = candidates[args.panel_index]
    return selected.center_x, selected.center_y, args.panel_index


def save_annotated(
    frame: np.ndarray,
    candidates: list[PanelCandidate],
    path: Path,
    selected_index: Optional[int] = None,
) -> None:
    """Save candidate boxes for test evidence."""
    output = frame.copy()
    for index, candidate in enumerate(candidates):
        thickness = 3 if index == selected_index else 2
        cv2.rectangle(
            output,
            (candidate.x, candidate.y),
            (candidate.x + candidate.w, candidate.y + candidate.h),
            (255, 255, 255),
            thickness,
        )
        cv2.putText(
            output,
            f'#{index}',
            (candidate.x, max(20, candidate.y - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )
    cv2.imwrite(str(path), output)


def build_parser() -> argparse.ArgumentParser:
    """Build field-test CLI."""
    parser = argparse.ArgumentParser(
        description='3m photo -> metric panel target -> low-altitude reacquisition'
    )
    parser.add_argument('--image', help='Use an existing survey image')
    parser.add_argument('--camera-index', type=int, default=0)
    parser.add_argument('--width', type=int, default=1920)
    parser.add_argument('--height', type=int, default=1080)
    parser.add_argument('--panel-index', type=int, default=0)
    parser.add_argument('--center', type=parse_pair, help='Panel center X,Y pixels')
    parser.add_argument('--bbox', type=parse_bbox, help='Panel bbox X,Y,W,H pixels')
    parser.add_argument('--interactive', action='store_true')
    parser.add_argument('--min-area-ratio', type=float, default=0.015)
    parser.add_argument('--max-area-ratio', type=float, default=0.90)

    parser.add_argument('--reference-distance-m', type=float, default=3.0)
    parser.add_argument('--reference-width-m', type=float, default=3.9)
    parser.add_argument('--reference-height-m', type=float, default=2.2)
    parser.add_argument('--approach-distance-m', type=float, default=1.0)
    parser.add_argument('--camera-yaw-offset-deg', type=float, default=0.0)
    parser.add_argument('--invert-horizontal', action='store_true')
    parser.add_argument('--invert-vertical', action='store_true')
    parser.add_argument('--expected-survey-height-m', type=float, default=3.0)
    parser.add_argument('--survey-height-tolerance-m', type=float, default=0.40)
    parser.add_argument('--max-tilt-deg', type=float, default=7.0)
    parser.add_argument('--allow-tilt', action='store_true')

    parser.add_argument('--pose-topic', default='/mavros/local_position/pose')
    parser.add_argument('--range-topic', default='/distance/filtered')
    parser.add_argument('--target-topic', default='/survey/panel_target_local')
    parser.add_argument('--json-topic', default='/survey/panel_target_json')
    parser.add_argument('--telemetry-timeout-s', type=float, default=5.0)
    parser.add_argument('--publish-rate-hz', type=float, default=10.0)
    parser.add_argument(
        '--publish-only',
        action='store_true',
        help='Publish the target and exit without low-altitude verification',
    )
    parser.add_argument(
        '--verify-wait-s',
        type=float,
        default=0.0,
        help='Wait fixed seconds instead of pressing Enter before verification',
    )
    parser.add_argument(
        '--output-dir',
        default='~/da_daka_logs/panel_reacquisition_test',
    )
    return parser


def main() -> int:
    """Run the field test."""
    args = build_parser().parse_args()
    if args.width <= 0 or args.height <= 0:
        print('ERROR: image dimensions must be positive', file=sys.stderr)
        return 2
    if not 0.0 < args.min_area_ratio < args.max_area_ratio <= 1.0:
        print('ERROR: invalid panel area ratio bounds', file=sys.stderr)
        return 2

    try:
        import rclpy
        from geometry_msgs.msg import PoseStamped
        from rclpy.node import Node
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import Range
        from std_msgs.msg import String
    except ImportError:
        print(
            'ERROR: ROS 2 Python environment is not sourced. '
            'source /opt/ros/jazzy/setup.bash first.',
            file=sys.stderr,
        )
        return 2

    class SurveyNode(Node):
        """Read capture telemetry and publish metric panel targets only."""

        def __init__(self) -> None:
            super().__init__('panel_reacquisition_test')
            self.pose: Optional[PoseStamped] = None
            self.distance_m: Optional[float] = None
            self.pose_time_s: Optional[float] = None
            self.range_time_s: Optional[float] = None
            self.create_subscription(
                PoseStamped,
                args.pose_topic,
                self._pose_callback,
                qos_profile_sensor_data,
            )
            self.create_subscription(
                Range,
                args.range_topic,
                self._range_callback,
                qos_profile_sensor_data,
            )
            latched_qos = QoSProfile(
                depth=1,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
            )
            self.target_pub = self.create_publisher(
                PoseStamped,
                args.target_topic,
                latched_qos,
            )
            self.json_pub = self.create_publisher(
                String,
                args.json_topic,
                latched_qos,
            )

        def _pose_callback(self, message: PoseStamped) -> None:
            self.pose = message
            self.pose_time_s = time.monotonic()

        def _range_callback(self, message: Range) -> None:
            if math.isfinite(float(message.range)) and message.range > 0.0:
                self.distance_m = float(message.range)
                self.range_time_s = time.monotonic()

        def ready(self) -> bool:
            now_s = time.monotonic()
            return (
                self.pose is not None
                and self.pose_time_s is not None
                and now_s - self.pose_time_s <= args.telemetry_timeout_s
                and self.distance_m is not None
                and self.range_time_s is not None
                and now_s - self.range_time_s <= args.telemetry_timeout_s
            )

    output_root = Path(args.output_dir).expanduser()
    run_dir = output_root / datetime.now().strftime('%Y%m%d_%H%M%S')
    run_dir.mkdir(parents=True, exist_ok=True)

    rclpy.init()
    node = SurveyNode()
    try:
        deadline = time.monotonic() + args.telemetry_timeout_s
        while rclpy.ok() and time.monotonic() < deadline and not node.ready():
            rclpy.spin_once(node, timeout_sec=0.05)
        if not node.ready() or node.pose is None or node.distance_m is None:
            raise RuntimeError(
                'fresh /mavros/local_position/pose and /distance/filtered '
                'were not available'
            )

        pose = node.pose
        distance_m = node.distance_m
        orientation = pose.pose.orientation
        roll, pitch, yaw = quaternion_to_rpy(
            orientation.x,
            orientation.y,
            orientation.z,
            orientation.w,
        )
        tilt_deg = max(abs(math.degrees(roll)), abs(math.degrees(pitch)))
        if tilt_deg > args.max_tilt_deg and not args.allow_tilt:
            raise RuntimeError(
                f'roll/pitch tilt {tilt_deg:.1f}deg exceeds '
                f'{args.max_tilt_deg:.1f}deg; hover level before capture'
            )
        if (
            abs(distance_m - args.expected_survey_height_m)
            > args.survey_height_tolerance_m
        ):
            print(
                f'[WARN] LiDAR={distance_m:.3f}m. Calculation uses this '
                'measured value instead of assuming exactly 3.0m.'
            )

        survey_path = run_dir / 'survey.jpg'
        if args.image:
            frame = cv2.imread(args.image, cv2.IMREAD_COLOR)
            if frame is None:
                raise RuntimeError(f'cannot read image: {args.image}')
            cv2.imwrite(str(survey_path), frame)
        else:
            frame = capture_frame(
                width=args.width,
                height=args.height,
                camera_index=args.camera_index,
                output_path=survey_path,
            )

        candidates = detect_panel_candidates(
            frame,
            min_area_ratio=args.min_area_ratio,
            max_area_ratio=args.max_area_ratio,
        )
        center_x, center_y, selected_index = choose_center(
            frame,
            candidates,
            args,
        )
        save_annotated(
            frame,
            candidates,
            run_dir / 'survey_annotated.jpg',
            selected_index,
        )

        target = build_panel_target(
            capture_east_m=float(pose.pose.position.x),
            capture_north_m=float(pose.pose.position.y),
            capture_up_m=float(pose.pose.position.z),
            yaw_enu_rad=yaw,
            lidar_distance_m=distance_m,
            panel_pixel_x=center_x,
            panel_pixel_y=center_y,
            image_width=frame.shape[1],
            image_height=frame.shape[0],
            approach_distance_m=args.approach_distance_m,
            reference_distance_m=args.reference_distance_m,
            reference_width_m=args.reference_width_m,
            reference_height_m=args.reference_height_m,
            camera_yaw_offset_rad=math.radians(args.camera_yaw_offset_deg),
            invert_horizontal=args.invert_horizontal,
            invert_vertical=args.invert_vertical,
        )

        payload = {
            'coordinate_frame': 'MAVROS_LOCAL_ENU',
            'purpose': 'coarse_panel_approach',
            'capture_lidar_m': distance_m,
            'capture_pose_enu_m': {
                'east': float(pose.pose.position.x),
                'north': float(pose.pose.position.y),
                'up': float(pose.pose.position.z),
            },
            'capture_attitude_deg': {
                'roll': math.degrees(roll),
                'pitch': math.degrees(pitch),
                'yaw_enu': math.degrees(yaw),
            },
            'panel_center_px': {'x': center_x, 'y': center_y},
            'relative_body_m': {
                'forward': target.forward_m,
                'right': target.right_m,
            },
            'target_enu_m': {
                'east': target.east_m,
                'north': target.north_m,
                'up': target.up_m,
            },
            'target_enu_cm': {
                'east': target.east_m * 100.0,
                'north': target.north_m * 100.0,
                'up': target.up_m * 100.0,
            },
            'auto_candidate_count': len(candidates),
            'survey_image': str(survey_path),
        }

        target_msg = PoseStamped()
        target_msg.header.frame_id = 'map'
        target_msg.pose.position.x = target.east_m
        target_msg.pose.position.y = target.north_m
        target_msg.pose.position.z = target.up_m
        target_msg.pose.orientation = orientation
        json_msg = String(data=json.dumps(payload, separators=(',', ':')))

        report_path = run_dir / 'panel_target.json'
        report_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding='utf-8',
        )

        print('\n=== HIGH-ALTITUDE SURVEY RESULT ===')
        print(
            f'LiDAR height: {distance_m:.3f} m | '
            f'panel center: ({center_x:.1f}, {center_y:.1f}) px'
        )
        print(
            f'relative: forward={target.forward_m:+.3f} m, '
            f'right={target.right_m:+.3f} m'
        )
        print(
            f'MAVROS local ENU: E={target.east_m:+.3f} m, '
            f'N={target.north_m:+.3f} m, U={target.up_m:+.3f} m'
        )
        print(
            f'centimeters: E={target.east_m * 100:+.1f} cm, '
            f'N={target.north_m * 100:+.1f} cm, '
            f'U={target.up_m * 100:+.1f} cm'
        )
        print(f'control target topic: {args.target_topic}')
        print(f'JSON detail topic: {args.json_topic}')
        print(f'log: {report_path}')

        publish_end = time.monotonic() + 3.0
        period = 1.0 / args.publish_rate_hz
        while rclpy.ok() and time.monotonic() < publish_end:
            target_msg.header.stamp = node.get_clock().now().to_msg()
            node.target_pub.publish(target_msg)
            node.json_pub.publish(json_msg)
            rclpy.spin_once(node, timeout_sec=min(period, 0.05))

        if args.publish_only:
            print('[DONE] Target published. No vehicle command was sent.')
            return 0

        print(
            '\n제어 프로그램이 위 ENU 좌표로 이동하고 '
            f'약 {args.approach_distance_m:.2f}m 고도까지 내려간 뒤 '
            '검증 촬영을 진행합니다.'
        )
        if args.verify_wait_s > 0.0:
            print(f'{args.verify_wait_s:.1f}s 후 자동 검증 촬영...')
            wait_end = time.monotonic() + args.verify_wait_s
            while time.monotonic() < wait_end:
                node.target_pub.publish(target_msg)
                rclpy.spin_once(node, timeout_sec=0.05)
        else:
            input('이동 완료 후 Enter를 누르세요: ')

        verify_path = run_dir / 'verify_low_altitude.jpg'
        verify_frame = capture_frame(
            width=args.width,
            height=args.height,
            camera_index=args.camera_index,
            output_path=verify_path,
        )
        verify_candidates = detect_panel_candidates(
            verify_frame,
            min_area_ratio=args.min_area_ratio,
            max_area_ratio=args.max_area_ratio,
        )
        save_annotated(
            verify_frame,
            verify_candidates,
            run_dir / 'verify_low_altitude_annotated.jpg',
            0 if verify_candidates else None,
        )

        payload['verification'] = {
            'auto_rectangle_found': bool(verify_candidates),
            'candidate_count': len(verify_candidates),
            'image': str(verify_path),
        }
        report_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding='utf-8',
        )

        print('\n=== LOW-ALTITUDE FRAME CHECK ===')
        if verify_candidates:
            print(
                'AUTO_VERIFY=PASS: panel-like rectangle exists in the '
                'low-altitude camera frame.'
            )
        else:
            print(
                'AUTO_VERIFY=INCONCLUSIVE: coarse rectangle detector found '
                'nothing. Inspect the saved image manually; this test detector '
                'is not the production panel AI model.'
            )
        print(f'verification image: {verify_path}')
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
