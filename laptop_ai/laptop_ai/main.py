"""Laptop-only video inference process; it never sends flight commands."""

from __future__ import annotations

import argparse
import logging
import sys
import time

from laptop_ai.config import AppConfig, load_config
from laptop_ai.debug_view import DebugView
from laptop_ai.detector_base import BaseDetector
from laptop_ai.health_monitor import HealthMonitor
from laptop_ai.onnx_detector import OnnxDetector
from laptop_ai.opencv_detector import OpenCvDetector
from laptop_ai.performance import configure_opencv
from laptop_ai.udp_result_sender import UdpResultSender
from laptop_ai.video_receiver import VideoReceiver


logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Receive Pi video, run dirt inference, and send UDP JSON results"
    )
    parser.add_argument("--config", required=True, help="Path to laptop_ai YAML config")
    return parser.parse_args()


def create_detector(config: AppConfig) -> BaseDetector:
    if config.detector.backend == "opencv":
        return OpenCvDetector(config.detector)
    if config.detector.backend == "onnx":
        return OnnxDetector(config.detector, config.performance)
    raise ValueError(f"unsupported detector backend: {config.detector.backend}")


def run(config: AppConfig) -> int:
    configure_opencv(config.performance)
    receiver = VideoReceiver(config.video)
    detector = create_detector(config)
    sender = UdpResultSender(
        config.network.destination_host,
        config.network.destination_port,
        config.network.source_id,
        max_packet_bytes=config.network.max_packet_bytes,
    )
    debug_view = DebugView(config.debug.show_window, config.debug.save_video)
    health = HealthMonitor(config.debug.summary_interval_s)
    last_frame_id = 0
    last_no_detection_send_s = -float("inf")

    logger.info(
        "starting source=%r backend=%s detector=%s destination=%s:%d source_id=%s session=%s",
        config.video.source,
        config.video.backend,
        config.detector.backend,
        config.network.destination_host,
        config.network.destination_port,
        config.network.source_id,
        sender.session_id,
    )
    receiver.start()
    try:
        while True:
            packet = receiver.read_latest(last_frame_id, timeout_s=0.25)
            if packet is None:
                health.metrics.reconnects = receiver.reconnect_count
                health.metrics.dropped_frames = receiver.dropped_frames
                health.maybe_log(logger, receiver.state.value)
                continue
            last_frame_id = packet.frame_id
            health.metrics.received_frames += 1
            health.metrics.last_frame_id = packet.frame_id
            if receiver.is_stale(packet):
                logger.warning("discarding stale frame_id=%d", packet.frame_id)
                continue
            if (
                (health.metrics.received_frames - 1)
                % config.video.process_every_n_frames
                != 0
            ):
                continue

            result = detector.detect(packet)
            result.validate(require_transport=False)
            health.metrics.processed_frames += 1
            health.metrics.last_inference_ms = result.inference_time_ms
            health.metrics.last_confidence = result.confidence
            health.metrics.last_end_to_end_ms = max(
                0.0, (time.time_ns() - result.capture_timestamp_ns) / 1e6
            )
            if result.dirt_found:
                health.metrics.detections += 1

            now_s = time.monotonic()
            should_send = result.dirt_found or (
                config.network.send_no_detection
                and now_s - last_no_detection_send_s
                >= config.network.heartbeat_interval_s
            )
            if should_send:
                try:
                    wire_result = sender.send(result)
                    health.metrics.udp_sent += 1
                    if not result.dirt_found:
                        last_no_detection_send_s = now_s
                    logger.debug(
                        "sent frame=%d sequence=%d dirt=%s confidence=%.3f bytes_session=%s",
                        wire_result.frame_id,
                        wire_result.sequence,
                        wire_result.dirt_found,
                        wire_result.confidence,
                        wire_result.session_id,
                    )
                except (OSError, ValueError) as exc:
                    health.metrics.udp_failures += 1
                    logger.error("UDP result send failed for frame=%d: %s", packet.frame_id, exc)

            if not debug_view.render(packet.frame, result):
                logger.info("debug window requested shutdown")
                break
            health.metrics.reconnects = receiver.reconnect_count
            health.metrics.dropped_frames = receiver.dropped_frames
            health.maybe_log(logger, receiver.state.value)
    except KeyboardInterrupt:
        logger.info("Ctrl+C received")
    finally:
        receiver.close()
        detector.close()
        sender.close()
        debug_view.close()
        logger.info(
            "stopped frames=%d processed=%d udp_ok=%d udp_fail=%d dropped=%d",
            health.metrics.received_frames,
            health.metrics.processed_frames,
            health.metrics.udp_sent,
            health.metrics.udp_failures,
            receiver.dropped_frames,
        )
    return 0


def main() -> int:
    args = parse_args()
    try:
        config = load_config(args.config)
        logging.basicConfig(
            level=getattr(logging, config.debug.log_level.upper(), logging.INFO),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        return run(config)
    except (OSError, RuntimeError, ValueError) as exc:
        logging.basicConfig(level=logging.INFO)
        logger.error("startup failed: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
