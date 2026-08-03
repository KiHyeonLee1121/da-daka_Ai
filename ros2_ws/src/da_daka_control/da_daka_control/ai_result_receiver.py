"""Receive laptop UDP JSON, validate it, and publish safe ROS 2 state."""

from __future__ import annotations

from dataclasses import replace
import json
import socket
import time
from typing import Optional

from da_daka_interfaces.msg import DirtDetection
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool, String

from da_daka_control.ai_result_protocol import (
    AiResult,
    FreshnessMonitor,
    FreshnessState,
    PacketProcessor,
    ValidationConfig,
)


class AiResultReceiverNode(Node):
    """Bridge untrusted UDP input into validated, fail-closed ROS topics."""

    def __init__(self) -> None:
        """Configure validation, publishers and the non-blocking UDP socket."""
        super().__init__("ai_result_receiver")
        self._declare_parameters()
        bind_address = str(self.get_parameter("bind_address").value)
        port = int(self.get_parameter("port").value)
        result_topic = str(self.get_parameter("result_topic").value)
        health_topic = str(self.get_parameter("health_topic").value)
        state_topic = str(self.get_parameter("state_topic").value)
        self._max_result_age_s = float(self.get_parameter("max_result_age_s").value)
        self._heartbeat_timeout_s = float(
            self.get_parameter("heartbeat_timeout_s").value
        )
        minimum_confidence = float(
            self.get_parameter("minimum_confidence").value
        )
        allowed_source_id = str(
            self.get_parameter("allowed_source_id").value
        )
        use_sender_age = bool(
            self.get_parameter("use_sender_timestamp_for_age").value
        )
        future_tolerance_s = float(
            self.get_parameter("future_timestamp_tolerance_s").value
        )
        poll_rate_hz = float(self.get_parameter("poll_rate_hz").value)
        self._max_packet_bytes = int(
            self.get_parameter("max_packet_bytes").value
        )
        self._summary_interval_s = float(
            self.get_parameter("summary_interval_s").value
        )
        self._validate_parameters(port, poll_rate_hz, allowed_source_id)

        self._processor = PacketProcessor(
            ValidationConfig(
                allowed_source_id=allowed_source_id,
                minimum_confidence=minimum_confidence,
                max_result_age_s=self._max_result_age_s,
                use_sender_timestamp_for_age=use_sender_age,
                future_timestamp_tolerance_s=future_tolerance_s,
            )
        )
        self._freshness = FreshnessMonitor()
        self._last_result: Optional[AiResult] = None
        self._last_detection_key = None
        self._last_health: Optional[bool] = None
        self._last_state_key = None
        self._last_freshness_reason = "no_result"
        self._last_summary_s = time.monotonic()
        self._last_rejection_log_s = -float("inf")

        latched_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._result_publisher = self.create_publisher(
            DirtDetection,
            result_topic,
            latched_qos,
        )
        self._health_publisher = self.create_publisher(
            Bool,
            health_topic,
            latched_qos,
        )
        self._state_publisher = self.create_publisher(
            String,
            state_topic,
            latched_qos,
        )

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((bind_address, port))
        self._socket.setblocking(False)
        self._timer = self.create_timer(1.0 / poll_rate_hz, self._poll)
        self._publish_health(False)
        self._publish_state(
            FreshnessState(False, False, float("inf"), "no_result")
        )
        age_mode = "sender wall clock" if use_sender_age else "local receive monotonic"
        self.get_logger().info(
            f"AI UDP receiver bound to {bind_address}:{port}; "
            f"source={allowed_source_id}; freshness={age_mode}"
        )

    def _declare_parameters(self) -> None:
        self.declare_parameter("bind_address", "0.0.0.0")
        self.declare_parameter("port", 5005)
        self.declare_parameter("result_topic", "/ai/detection_result")
        self.declare_parameter("health_topic", "/ai/health")
        self.declare_parameter("state_topic", "/ai/receiver_state")
        self.declare_parameter("max_result_age_s", 0.4)
        self.declare_parameter("heartbeat_timeout_s", 1.0)
        self.declare_parameter("minimum_confidence", 0.5)
        self.declare_parameter("allowed_source_id", "laptop-ai-01")
        self.declare_parameter("use_sender_timestamp_for_age", False)
        self.declare_parameter("future_timestamp_tolerance_s", 1.0)
        self.declare_parameter("poll_rate_hz", 100.0)
        self.declare_parameter("max_packet_bytes", 4096)
        self.declare_parameter("summary_interval_s", 5.0)

    def _validate_parameters(
        self,
        port: int,
        poll_rate_hz: float,
        allowed_source_id: str,
    ) -> None:
        if not 1 <= port <= 65535:
            raise ValueError("port must be within [1, 65535]")
        if poll_rate_hz <= 0.0:
            raise ValueError("poll_rate_hz must be positive")
        if self._max_result_age_s <= 0.0 or self._heartbeat_timeout_s <= 0.0:
            raise ValueError("freshness timeouts must be positive")
        if not allowed_source_id:
            raise ValueError("allowed_source_id cannot be empty")
        if self._max_packet_bytes < 512:
            raise ValueError("max_packet_bytes must be at least 512")

    def _poll(self) -> None:
        self._drain_socket()
        now_monotonic_ns = time.monotonic_ns()
        state = self._freshness.snapshot(
            now_monotonic_ns=now_monotonic_ns,
            max_result_age_s=self._max_result_age_s,
            heartbeat_timeout_s=self._heartbeat_timeout_s,
        )
        if (
            state.invalid_reason == "stale_result"
            and self._last_freshness_reason != "stale_result"
        ):
            self._processor.counters.stale += 1
        self._last_freshness_reason = state.invalid_reason
        self._publish_health(state.healthy)
        if self._last_result is not None:
            state_result = replace(
                self._last_result,
                valid=state.result_valid,
                result_age_s=state.result_age_s,
                invalid_reason=state.invalid_reason,
            )
            self._publish_detection_if_changed(state_result)
        self._publish_state(state)
        self._maybe_log_summary()

    def _drain_socket(self) -> None:
        for _ in range(100):
            try:
                packet, _address = self._socket.recvfrom(
                    self._max_packet_bytes + 1
                )
            except BlockingIOError:
                return
            except OSError as exc:
                self.get_logger().error(f"UDP receive error: {exc}")
                return
            if len(packet) > self._max_packet_bytes:
                self._processor.counters.rejected += 1
                self._log_rejection("packet_too_large", str(len(packet)))
                continue
            outcome = self._processor.process(packet)
            if outcome.result is None:
                self._log_rejection(outcome.error_code, outcome.error_message)
                continue
            receive_ns = time.monotonic_ns()
            self._last_result = outcome.result
            self._freshness.observe(outcome.result, receive_ns)
            self._publish_detection_if_changed(outcome.result, force=True)

    def _log_rejection(self, code: str, message: str) -> None:
        now_s = time.monotonic()
        if now_s - self._last_rejection_log_s >= 2.0:
            self.get_logger().warning(
                f"Rejected AI UDP packet: {code}: {message}"
            )
            self._last_rejection_log_s = now_s

    def _publish_detection_if_changed(
        self,
        result: AiResult,
        *,
        force: bool = False,
    ) -> None:
        key = (
            result.session_id,
            result.sequence,
            result.valid,
            result.invalid_reason,
        )
        if not force and key == self._last_detection_key:
            return
        message = DirtDetection()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = "laptop_ai"
        message.protocol_version = result.protocol_version
        message.source_id = result.source_id
        message.session_id = result.session_id
        message.frame_id = result.frame_id
        message.sequence = result.sequence
        message.dirt_found = result.dirt_found
        message.valid = result.valid
        message.centroid_x_norm = result.centroid_x_norm
        message.centroid_y_norm = result.centroid_y_norm
        message.bbox_x_norm = result.bbox_x_norm
        message.bbox_y_norm = result.bbox_y_norm
        message.bbox_w_norm = result.bbox_w_norm
        message.bbox_h_norm = result.bbox_h_norm
        message.area_ratio = result.area_ratio
        message.confidence = result.confidence
        message.inference_time_ms = result.inference_time_ms
        message.result_age_s = result.result_age_s
        message.invalid_reason = result.invalid_reason
        message.model_name = result.model_name
        self._result_publisher.publish(message)
        self._last_detection_key = key

    def _publish_health(self, healthy: bool) -> None:
        if healthy == self._last_health:
            return
        self._health_publisher.publish(Bool(data=healthy))
        self._last_health = healthy
        self.get_logger().info(f"AI health={healthy}")

    def _publish_state(self, state: FreshnessState) -> None:
        dirt_found = bool(self._last_result and self._last_result.dirt_found)
        movement_allowed = state.healthy and state.result_valid and dirt_found
        counters = self._processor.counters
        state_key = (
            state.healthy,
            state.result_valid,
            state.invalid_reason,
            movement_allowed,
            counters.accepted,
            counters.malformed,
            counters.stale,
            counters.out_of_order,
            counters.rejected,
        )
        if state_key == self._last_state_key:
            return
        payload = {
            "ai_health": state.healthy,
            "detection_valid": state.result_valid,
            "result_age_s": None if math_is_inf(state.result_age_s) else state.result_age_s,
            "invalid_reason": state.invalid_reason,
            "movement_allowed": movement_allowed,
            "spray_allowed": movement_allowed,
            "hold_requested": not movement_allowed,
            "zero_velocity_requested": not movement_allowed,
            "error_state": (
                "AI_HEARTBEAT_TIMEOUT"
                if state.invalid_reason == "heartbeat_timeout"
                else state.invalid_reason
            ),
            "accepted_packets": counters.accepted,
            "malformed_packets": counters.malformed,
            "stale_packets": counters.stale,
            "out_of_order_packets": counters.out_of_order,
            "rejected_packets": counters.rejected,
        }
        self._state_publisher.publish(
            String(data=json.dumps(payload, separators=(",", ":")))
        )
        self._last_state_key = state_key

    def _maybe_log_summary(self) -> None:
        now_s = time.monotonic()
        if now_s - self._last_summary_s < self._summary_interval_s:
            return
        result = self._last_result
        source = result.source_id if result else "-"
        session = result.session_id if result else "-"
        sequence = result.sequence if result else 0
        frame_id = result.frame_id if result else 0
        counters = self._processor.counters
        self.get_logger().info(
            f"AI UDP summary source={source} session={session} "
            f"sequence={sequence} frame={frame_id} health={self._last_health} "
            f"accepted={counters.accepted} malformed={counters.malformed} "
            f"stale={counters.stale} out_of_order={counters.out_of_order} "
            f"rejected={counters.rejected}"
        )
        self._last_summary_s = now_s

    def destroy_node(self) -> bool:
        """Close the UDP socket before normal ROS shutdown."""
        self._socket.close()
        return super().destroy_node()


def math_is_inf(value: float) -> bool:
    """Return true for either signed infinity without importing numpy."""
    return value == float("inf") or value == -float("inf")


def main(args=None) -> None:
    """Run the AI UDP receiver node."""
    rclpy.init(args=args)
    node = AiResultReceiverNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
