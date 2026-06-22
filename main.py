from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

from actuator.spray_command import create_spray_controller
from control.mavlink_bridge import MavlinkBridge
from control.mission_fsm import MissionFSM, MissionInputs
from control.visual_servo import MovementType, VisualServoController
from sensors.lidar_reader import create_lidar_reader
from utils.config_loader import load_config, set_nested
from utils.drawing import draw_debug_overlay
from utils.logger import MissionLogger, make_log_row
from utils.time_utils import now_s, timestamp_for_filename
from vision.camera import OpenCVCamera
from vision.hailo_dirt_detector import HailoDirtDetector
from vision.opencv_dirt_detector import OpenCVDirtDetector
from vision.panel_detector import PanelDetector
from vision.target_estimator import estimate_target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Solar panel dirt detection and selective spray MVP")
    parser.add_argument("--config", default="config/params.yaml", help="Path to YAML config")
    parser.add_argument("--video", default=None, help="Video file path; overrides camera.source")
    parser.add_argument("--dry-run", action="store_true", help="Force MAVLink and spray dry-run mode")
    parser.add_argument("--no-display", action="store_true", help="Disable OpenCV debug window")
    parser.add_argument("--save-video", action="store_true", help="Save debug overlay MP4")
    parser.add_argument("--max-frames", type=int, default=0, help="Optional loop limit for bench tests")
    return parser.parse_args()


def create_detector(config: dict):
    detector_config = config.get("detector", {})
    backend = str(detector_config.get("backend", "opencv")).lower()
    if backend == "hailo":
        return HailoDirtDetector(detector_config)
    if backend == "opencv":
        return OpenCVDirtDetector(detector_config)
    raise ValueError(f"Unsupported detector backend: {backend}")


def execute_command(mavlink: MavlinkBridge, spray_controller, output):
    command = output.command
    spray_event = None

    if command.command_type in {
        MovementType.MOVE_LEFT,
        MovementType.MOVE_RIGHT,
        MovementType.MOVE_FORWARD,
        MovementType.MOVE_BACKWARD,
        MovementType.APPROACH_PANEL,
        MovementType.RETREAT_FROM_PANEL,
    }:
        mavlink.send_velocity_setpoint(command.vx, command.vy, command.vz, command.yaw_rate)
    elif command.command_type == MovementType.STOP:
        mavlink.send_stop()
    elif command.command_type == MovementType.HOLD:
        mavlink.send_hold()

    if output.should_spray:
        mavlink.send_stop()
        spray_event = spray_controller.spray(output.spray_duration_s)

    return spray_event


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = parse_args()
    config_path = Path(args.config)
    config = load_config(config_path)

    if args.video:
        set_nested(config, "camera.source", args.video)
    if args.dry_run:
        set_nested(config, "mavlink.dry_run", True)
        set_nested(config, "spray.dry_run", True)
    if args.no_display:
        set_nested(config, "debug.show_window", False)
    if args.save_video:
        set_nested(config, "debug.save_video", True)

    camera = OpenCVCamera(config.get("camera", {}))
    panel_detector = PanelDetector(config.get("roi", {}))
    detector = create_detector(config)
    lidar = create_lidar_reader(config.get("lidar", {}))
    servo = VisualServoController(config.get("visual_servo", {}), config.get("lidar", {}))
    mavlink = MavlinkBridge(config.get("mavlink", {}))
    spray_controller = create_spray_controller(config.get("spray", {}), mavlink)
    fsm = MissionFSM(config.get("mission", {}), config.get("spray", {}))

    surface_config = config.get("surface", {})
    flight_config = config.get("flight", {})
    logging.info(
        "Test surface=%s low_altitude_mode=%s expected_height=%.2f-%.2fm",
        surface_config.get("type", "unknown"),
        flight_config.get("low_altitude_mode", False),
        float(flight_config.get("expected_height_min_m", 0.0)),
        float(flight_config.get("expected_height_max_m", 0.0)),
    )

    logger = MissionLogger(
        save_logs=bool(config.get("debug", {}).get("save_logs", True)),
        logs_dir=Path(__file__).resolve().parent / "logs",
    )

    show_window = bool(config.get("debug", {}).get("show_window", True))
    save_video = bool(config.get("debug", {}).get("save_video", False))
    max_mission_time_s = float(config.get("safety", {}).get("max_mission_time_s", 0.0))
    video_writer = None
    debug_video_path = None

    try:
        import cv2

        camera.open()
        mavlink.connect()
        mission_start_s = now_s()
        fsm.start(mission_start_s)
        frame_count = 0

        while True:
            loop_now_s = now_s()
            ok, frame = camera.read()
            if not ok or frame is None:
                logging.info("No more frames from source")
                break

            frame_count += 1
            frame_h, frame_w = frame.shape[:2]
            panel_roi = panel_detector.detect(frame)
            detection = detector.detect(frame, panel_roi.as_tuple() if panel_roi else None)
            target = estimate_target(detection, frame_w, frame_h)
            lidar_reading = lidar.read_distance()
            visual_command = servo.compute(
                frame_width=frame_w,
                frame_height=frame_h,
                target_centroid=target.centroid,
                lidar_distance_m=lidar_reading.distance_m if lidar_reading.valid else None,
            )

            fsm_inputs = MissionInputs(
                panel_found=panel_roi is not None,
                detection=detection,
                target=target,
                lidar=lidar_reading,
                visual_command=visual_command,
                timestamp=loop_now_s,
            )
            output = fsm.update(fsm_inputs)
            spray_event = execute_command(mavlink, spray_controller, output)

            overlay = draw_debug_overlay(
                frame,
                panel_roi,
                detection,
                target,
                lidar_reading,
                output.command,
                output.state,
                dry_run=mavlink.dry_run,
            )

            if save_video:
                if video_writer is None:
                    debug_video_path = Path(__file__).resolve().parent / "logs" / f"debug_{timestamp_for_filename()}.mp4"
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    fps = float(config.get("camera", {}).get("fps", 30))
                    video_writer = cv2.VideoWriter(str(debug_video_path), fourcc, fps, (frame_w, frame_h))
                video_writer.write(overlay)

            logger.log(
                make_log_row(
                    state=output.state,
                    detection=detection,
                    target=target,
                    lidar=lidar_reading,
                    command=output.command,
                    spray_event=spray_event,
                    retry_count=output.retry_count,
                    detection_streak=output.detection_streak,
                    spray_count=output.spray_count,
                    message=output.message,
                )
            )

            if show_window:
                cv2.imshow("daka_rpi debug", overlay)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    logging.info("Quit requested")
                    break

            if output.done or output.abort:
                logging.info("Mission terminal state: %s (%s)", output.state.value, output.message)
                break

            if max_mission_time_s > 0 and loop_now_s - mission_start_s >= max_mission_time_s:
                logging.warning("Mission time limit reached: %.1fs", max_mission_time_s)
                break

            if args.max_frames and frame_count >= args.max_frames:
                logging.info("Max frame limit reached: %d", args.max_frames)
                break

        if debug_video_path is not None:
            logging.info("Debug video saved: %s", debug_video_path)

    finally:
        try:
            mavlink.send_hold()
        except Exception as exc:  # pragma: no cover - best-effort shutdown
            logging.warning("Failed to send final hold: %s", exc)
        camera.release()
        lidar.close()
        spray_controller.close()
        mavlink.close()
        logger.close()
        if video_writer is not None:
            video_writer.release()
        if show_window:
            try:
                import cv2

                cv2.destroyAllWindows()
            except Exception:
                pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
