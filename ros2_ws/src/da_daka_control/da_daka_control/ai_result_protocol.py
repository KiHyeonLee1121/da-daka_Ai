"""Pure validation and freshness logic for laptop AI UDP results."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import math
import time
from typing import Any, Optional


PROTOCOL_VERSION = 1
REQUIRED_FIELDS = {
    "protocol_version",
    "source_id",
    "session_id",
    "frame_id",
    "capture_timestamp_ns",
    "inference_timestamp_ns",
    "send_timestamp_ns",
    "image_width",
    "image_height",
    "dirt_found",
    "centroid_x_norm",
    "centroid_y_norm",
    "bbox_x_norm",
    "bbox_y_norm",
    "bbox_w_norm",
    "bbox_h_norm",
    "area_ratio",
    "confidence",
    "inference_time_ms",
    "model_name",
    "sequence",
}


class ProtocolValidationError(ValueError):
    """Classify an unsafe or malformed protocol value with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        """Store the stable rejection code with its diagnostic message."""
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ValidationConfig:
    """Receiver-side allowlist, confidence and freshness policy."""

    allowed_source_id: str
    minimum_confidence: float = 0.5
    max_result_age_s: float = 0.4
    use_sender_timestamp_for_age: bool = False
    future_timestamp_tolerance_s: float = 1.0

    def __post_init__(self) -> None:
        """Reject unsafe receiver policy values at construction time."""
        if not self.allowed_source_id:
            raise ValueError("allowed_source_id cannot be empty")
        if not 0.0 <= self.minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be within [0, 1]")
        if self.max_result_age_s <= 0.0:
            raise ValueError("max_result_age_s must be positive")
        if self.future_timestamp_tolerance_s < 0.0:
            raise ValueError("future_timestamp_tolerance_s cannot be negative")


@dataclass(frozen=True)
class AiResult:
    """Fully parsed protocol-v1 result plus receiver validity fields."""

    protocol_version: int
    source_id: str
    session_id: str
    frame_id: int
    capture_timestamp_ns: int
    inference_timestamp_ns: int
    send_timestamp_ns: int
    image_width: int
    image_height: int
    dirt_found: bool
    centroid_x_norm: float
    centroid_y_norm: float
    bbox_x_norm: float
    bbox_y_norm: float
    bbox_w_norm: float
    bbox_h_norm: float
    area_ratio: float
    confidence: float
    inference_time_ms: float
    model_name: str
    sequence: int
    valid: bool = True
    result_age_s: float = 0.0
    invalid_reason: str = ""


@dataclass(frozen=True)
class ProcessOutcome:
    """Non-throwing packet processing result for an untrusted datagram."""

    result: Optional[AiResult]
    error_code: str = ""
    error_message: str = ""


@dataclass
class ProtocolCounters:
    """Receiver counters grouped by safety-relevant rejection class."""

    accepted: int = 0
    malformed: int = 0
    stale: int = 0
    out_of_order: int = 0
    rejected: int = 0


@dataclass(frozen=True)
class FreshnessState:
    """Current local heartbeat and detection freshness decision."""

    healthy: bool
    result_valid: bool
    result_age_s: float
    invalid_reason: str


class SequenceTracker:
    """Accept monotonic sequence/frame IDs and reset on a new session."""

    def __init__(self) -> None:
        """Initialize an empty session ordering baseline."""
        self.session_id: Optional[str] = None
        self.last_sequence: Optional[int] = None
        self.last_frame_id: Optional[int] = None

    def accept(self, result: AiResult) -> None:
        """Accept a newer result or raise a classified ordering error."""
        if result.session_id != self.session_id:
            self.session_id = result.session_id
            self.last_sequence = result.sequence
            self.last_frame_id = result.frame_id
            return
        if self.last_sequence is not None and result.sequence <= self.last_sequence:
            code = (
                "duplicate_sequence"
                if result.sequence == self.last_sequence
                else "past_sequence"
            )
            raise ProtocolValidationError(
                code,
                f"sequence {result.sequence} is not newer than "
                f"{self.last_sequence}",
            )
        if self.last_frame_id is not None and result.frame_id <= self.last_frame_id:
            code = (
                "duplicate_frame"
                if result.frame_id == self.last_frame_id
                else "past_frame"
            )
            raise ProtocolValidationError(
                code,
                f"frame_id {result.frame_id} is not newer than "
                f"{self.last_frame_id}",
            )
        self.last_sequence = result.sequence
        self.last_frame_id = result.frame_id


class FreshnessMonitor:
    """Use local monotonic receive time unless synchronized sender age is enabled."""

    def __init__(self) -> None:
        """Initialize without an accepted result."""
        self.last_result: Optional[AiResult] = None
        self.last_receive_monotonic_ns: Optional[int] = None

    def observe(self, result: AiResult, receive_monotonic_ns: int) -> None:
        """Record the last accepted result and its local receive time."""
        self.last_result = result
        self.last_receive_monotonic_ns = receive_monotonic_ns

    def snapshot(
        self,
        *,
        now_monotonic_ns: int,
        max_result_age_s: float,
        heartbeat_timeout_s: float,
    ) -> FreshnessState:
        """Return fail-closed freshness state at a local monotonic time."""
        if self.last_result is None or self.last_receive_monotonic_ns is None:
            return FreshnessState(False, False, math.inf, "no_result")
        receive_age_s = max(
            0.0,
            (now_monotonic_ns - self.last_receive_monotonic_ns) / 1e9,
        )
        total_age_s = self.last_result.result_age_s + receive_age_s
        healthy = receive_age_s <= heartbeat_timeout_s
        if not healthy:
            return FreshnessState(False, False, total_age_s, "heartbeat_timeout")
        if total_age_s > max_result_age_s:
            return FreshnessState(True, False, total_age_s, "stale_result")
        if not self.last_result.valid:
            return FreshnessState(True, False, total_age_s, self.last_result.invalid_reason)
        return FreshnessState(True, True, total_age_s, "")


class PacketProcessor:
    """Never raise for untrusted UDP input; return a classified outcome."""

    def __init__(self, config: ValidationConfig) -> None:
        """Create a processor with independent ordering state and counters."""
        self.config = config
        self.tracker = SequenceTracker()
        self.counters = ProtocolCounters()

    def process(self, packet: bytes | str, *, now_wall_ns: int | None = None) -> ProcessOutcome:
        """Validate one datagram without allowing bad input to escape."""
        try:
            result = decode_and_validate(packet, self.config, now_wall_ns=now_wall_ns)
            self.tracker.accept(result)
        except ProtocolValidationError as exc:
            if exc.code in {"invalid_json", "invalid_encoding", "not_object"}:
                self.counters.malformed += 1
            elif exc.code in {
                "duplicate_sequence",
                "past_sequence",
                "duplicate_frame",
                "past_frame",
            }:
                self.counters.out_of_order += 1
            elif exc.code == "stale_result":
                self.counters.stale += 1
            else:
                self.counters.rejected += 1
            return ProcessOutcome(None, exc.code, str(exc))
        self.counters.accepted += 1
        return ProcessOutcome(result)


def decode_and_validate(
    packet: bytes | str,
    config: ValidationConfig,
    *,
    now_wall_ns: int | None = None,
) -> AiResult:
    """Parse and validate one complete protocol-v1 JSON packet."""
    try:
        raw: Any = json.loads(packet)
    except UnicodeDecodeError as exc:
        raise ProtocolValidationError("invalid_encoding", str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise ProtocolValidationError("invalid_json", str(exc)) from exc
    if not isinstance(raw, dict):
        raise ProtocolValidationError("not_object", "AI result JSON must be an object")
    missing = sorted(REQUIRED_FIELDS.difference(raw))
    if missing:
        raise ProtocolValidationError("missing_fields", "missing fields: " + ", ".join(missing))

    values = {name: raw[name] for name in REQUIRED_FIELDS}
    _validate_integer_fields(values)
    _validate_string_and_bool_fields(values, config)
    _validate_float_fields(values)
    try:
        result = AiResult(**values)
    except TypeError as exc:
        raise ProtocolValidationError("invalid_fields", str(exc)) from exc
    _validate_semantics(result)

    result_age_s = 0.0
    if config.use_sender_timestamp_for_age:
        wall_ns = time.time_ns() if now_wall_ns is None else now_wall_ns
        result_age_s = (wall_ns - result.send_timestamp_ns) / 1e9
        if result_age_s < -config.future_timestamp_tolerance_s:
            raise ProtocolValidationError(
                "future_timestamp",
                f"sender timestamp is {-result_age_s:.3f}s in the future",
            )
        result_age_s = max(0.0, result_age_s)
        if result_age_s > config.max_result_age_s:
            raise ProtocolValidationError(
                "stale_result",
                f"result age {result_age_s:.3f}s exceeds {config.max_result_age_s:.3f}s",
            )

    valid = True
    invalid_reason = ""
    if result.inference_time_ms / 1000.0 > config.max_result_age_s:
        valid = False
        invalid_reason = "inference_too_slow"
    elif result.dirt_found and result.confidence < config.minimum_confidence:
        valid = False
        invalid_reason = "below_minimum_confidence"
    return replace(
        result,
        valid=valid,
        result_age_s=result_age_s,
        invalid_reason=invalid_reason,
    )


def _validate_integer_fields(values: dict[str, Any]) -> None:
    for name in (
        "protocol_version",
        "frame_id",
        "capture_timestamp_ns",
        "inference_timestamp_ns",
        "send_timestamp_ns",
        "image_width",
        "image_height",
        "sequence",
    ):
        value = values[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ProtocolValidationError(
                "invalid_integer",
                f"{name} must be a non-negative integer",
            )
    if values["protocol_version"] != PROTOCOL_VERSION:
        raise ProtocolValidationError(
            "protocol_version",
            f"expected protocol {PROTOCOL_VERSION}, got {values['protocol_version']}",
        )
    if values["image_width"] <= 0 or values["image_height"] <= 0:
        raise ProtocolValidationError("image_dimensions", "image dimensions must be positive")


def _validate_string_and_bool_fields(values: dict[str, Any], config: ValidationConfig) -> None:
    for name in ("source_id", "session_id", "model_name"):
        if not isinstance(values[name], str) or not values[name]:
            raise ProtocolValidationError("invalid_string", f"{name} must be a non-empty string")
    if values["source_id"] != config.allowed_source_id:
        raise ProtocolValidationError(
            "source_id",
            f"source {values['source_id']!r} is not allowed",
        )
    if not isinstance(values["dirt_found"], bool):
        raise ProtocolValidationError("invalid_boolean", "dirt_found must be boolean")


def _validate_float_fields(values: dict[str, Any]) -> None:
    names = (
        "centroid_x_norm",
        "centroid_y_norm",
        "bbox_x_norm",
        "bbox_y_norm",
        "bbox_w_norm",
        "bbox_h_norm",
        "area_ratio",
        "confidence",
        "inference_time_ms",
    )
    for name in names:
        value = values[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ProtocolValidationError("invalid_number", f"{name} must be numeric")
        if not math.isfinite(float(value)):
            raise ProtocolValidationError("non_finite", f"{name} must be finite")
        values[name] = float(value)
    for name in names[:-1]:
        if not 0.0 <= values[name] <= 1.0:
            raise ProtocolValidationError("normalized_range", f"{name} must be within [0, 1]")
    if values["inference_time_ms"] < 0.0:
        raise ProtocolValidationError("inference_time", "inference_time_ms cannot be negative")


def _validate_semantics(result: AiResult) -> None:
    if result.inference_timestamp_ns < result.capture_timestamp_ns:
        raise ProtocolValidationError("timestamp_order", "inference precedes capture")
    if result.send_timestamp_ns < result.inference_timestamp_ns:
        raise ProtocolValidationError("timestamp_order", "send precedes inference")
    if result.bbox_x_norm + result.bbox_w_norm > 1.0 + 1e-6:
        raise ProtocolValidationError("bbox_range", "bbox exceeds normalized image width")
    if result.bbox_y_norm + result.bbox_h_norm > 1.0 + 1e-6:
        raise ProtocolValidationError("bbox_range", "bbox exceeds normalized image height")
    if result.dirt_found:
        if result.bbox_w_norm <= 0.0 or result.bbox_h_norm <= 0.0:
            raise ProtocolValidationError("empty_bbox", "detection bbox must be non-empty")
        if result.confidence <= 0.0:
            raise ProtocolValidationError("confidence", "detection confidence must be positive")
    else:
        detection_values = (
            result.centroid_x_norm,
            result.centroid_y_norm,
            result.bbox_x_norm,
            result.bbox_y_norm,
            result.bbox_w_norm,
            result.bbox_h_norm,
            result.area_ratio,
            result.confidence,
        )
        if any(value != 0.0 for value in detection_values):
            raise ProtocolValidationError(
                "no_detection_values",
                "no-detection packets must use zero detection values",
            )
