"""Versioned compact JSON protocol for laptop AI results."""

from __future__ import annotations

import json
from typing import Any

from laptop_ai.detection_types import DetectionResult


def serialize_result(result: DetectionResult, *, max_packet_bytes: int = 4096) -> bytes:
    result.validate(require_transport=True)
    packet = json.dumps(
        result.to_dict(),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(packet) > max_packet_bytes:
        raise ValueError(f"UDP result is {len(packet)} bytes; limit is {max_packet_bytes}")
    return packet


def deserialize_result(packet: bytes | str) -> DetectionResult:
    try:
        raw: Any = json.loads(packet)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid result JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("result JSON must be an object")
    try:
        result = DetectionResult(**raw)
    except TypeError as exc:
        raise ValueError(f"invalid result fields: {exc}") from exc
    result.validate(require_transport=True)
    return result
