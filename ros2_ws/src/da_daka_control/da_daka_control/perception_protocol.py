"""Validation for untrusted laptop perception protocol version 3."""

from dataclasses import dataclass
import json
import math
from typing import Any, Optional


PROTOCOL_VERSION = 3
MODES = {'idle', 'survey', 'clean'}


class PerceptionProtocolError(ValueError):
    """Protocol error with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PanelPacket:
    """Validated panel rectangle from one laptop result."""

    candidate_id: int
    center_x_norm: float
    center_y_norm: float
    width_norm: float
    height_norm: float
    confidence: float


@dataclass(frozen=True)
class PerceptionPacket:
    """Validated survey or cleaning perception result."""

    protocol_version: int
    source_id: str
    session_id: str
    frame_id: int
    sequence: int
    capture_timestamp_ns: int
    inference_timestamp_ns: int
    send_timestamp_ns: int
    mode: str
    image_width: int
    image_height: int
    valid: bool
    panel_visible: bool
    target_panel_selected: bool
    target_panel_candidate_id: int
    panels: tuple[PanelPacket, ...]
    active_panel_id: int
    dirt_found: bool
    dirt_centroid_x_norm: float
    dirt_centroid_y_norm: float
    dirt_bbox_x_norm: float
    dirt_bbox_y_norm: float
    dirt_bbox_w_norm: float
    dirt_bbox_h_norm: float
    dirt_confidence: float
    total_dirty_area_ratio: float
    dirt_component_count: int
    target_component_area_ratio: float
    inference_time_ms: float
    invalid_reason: str
    model_name: str
    model_sha256: str
    dataset_version: str


@dataclass(frozen=True)
class ProtocolConfig:
    """Receiver allowlist and resource limits."""

    allowed_source_id: str
    maximum_panels: int = 32
    maximum_inference_time_ms: float = 1000.0

    def __post_init__(self) -> None:
        if not self.allowed_source_id:
            raise ValueError('allowed_source_id cannot be empty')
        if self.maximum_panels <= 0:
            raise ValueError('maximum_panels must be positive')
        if self.maximum_inference_time_ms <= 0.0:
            raise ValueError('maximum_inference_time_ms must be positive')


class SequenceTracker:
    """Reject duplicates and out-of-order results inside one session."""

    def __init__(self) -> None:
        self.session_id: Optional[str] = None
        self.sequence: Optional[int] = None
        self.frame_id: Optional[int] = None

    def accept(self, packet: PerceptionPacket) -> None:
        """Accept only a newer frame/sequence within the current session."""
        if packet.session_id != self.session_id:
            self.session_id = packet.session_id
            self.sequence = packet.sequence
            self.frame_id = packet.frame_id
            return
        if self.sequence is not None and packet.sequence <= self.sequence:
            raise PerceptionProtocolError(
                'sequence_order',
                f'sequence {packet.sequence} is not newer than {self.sequence}',
            )
        if self.frame_id is not None and packet.frame_id <= self.frame_id:
            raise PerceptionProtocolError(
                'frame_order',
                f'frame {packet.frame_id} is not newer than {self.frame_id}',
            )
        self.sequence = packet.sequence
        self.frame_id = packet.frame_id


def _integer(raw: dict[str, Any], name: str, *, signed: bool = False) -> int:
    value = raw.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PerceptionProtocolError('invalid_integer', f'{name} must be integer')
    if not signed and value < 0:
        raise PerceptionProtocolError(
            'invalid_integer', f'{name} must be non-negative'
        )
    return value


def _number(raw: dict[str, Any], name: str) -> float:
    value = raw.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PerceptionProtocolError('invalid_number', f'{name} must be numeric')
    result = float(value)
    if not math.isfinite(result):
        raise PerceptionProtocolError('invalid_number', f'{name} must be finite')
    return result


def _normalized(raw: dict[str, Any], name: str) -> float:
    value = _number(raw, name)
    if not 0.0 <= value <= 1.0:
        raise PerceptionProtocolError(
            'normalized_range', f'{name} must be within [0, 1]'
        )
    return value


def _string(raw: dict[str, Any], name: str, *, allow_empty: bool = False) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or (not value and not allow_empty):
        raise PerceptionProtocolError('invalid_string', f'{name} is invalid')
    return value


def _boolean(raw: dict[str, Any], name: str) -> bool:
    value = raw.get(name)
    if not isinstance(value, bool):
        raise PerceptionProtocolError('invalid_boolean', f'{name} must be boolean')
    return value


def _panel(raw: Any) -> PanelPacket:
    if not isinstance(raw, dict):
        raise PerceptionProtocolError('invalid_panel', 'panel must be an object')
    panel = PanelPacket(
        candidate_id=_integer(raw, 'candidate_id'),
        center_x_norm=_normalized(raw, 'center_x_norm'),
        center_y_norm=_normalized(raw, 'center_y_norm'),
        width_norm=_normalized(raw, 'width_norm'),
        height_norm=_normalized(raw, 'height_norm'),
        confidence=_normalized(raw, 'confidence'),
    )
    if min(panel.width_norm, panel.height_norm, panel.confidence) <= 0.0:
        raise PerceptionProtocolError(
            'invalid_panel', 'panel dimensions/confidence must be positive'
        )
    if panel.candidate_id <= 0:
        raise PerceptionProtocolError(
            'invalid_panel', 'panel candidate ID must be positive'
        )
    return panel


def decode_perception_packet(
    data: bytes | str,
    config: ProtocolConfig,
) -> PerceptionPacket:
    """Decode and completely validate one UDP JSON result."""
    try:
        raw = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PerceptionProtocolError('invalid_json', str(exc)) from exc
    if not isinstance(raw, dict):
        raise PerceptionProtocolError('not_object', 'packet must be an object')

    version = _integer(raw, 'protocol_version')
    if version != PROTOCOL_VERSION:
        raise PerceptionProtocolError(
            'protocol_version', f'expected {PROTOCOL_VERSION}, got {version}'
        )
    source_id = _string(raw, 'source_id')
    if source_id != config.allowed_source_id:
        raise PerceptionProtocolError('source_id', 'source is not allowed')
    mode = _string(raw, 'mode').lower()
    if mode not in MODES:
        raise PerceptionProtocolError('mode', f'unsupported mode {mode!r}')
    raw_panels = raw.get('panels')
    if not isinstance(raw_panels, list):
        raise PerceptionProtocolError('panels', 'panels must be an array')
    if len(raw_panels) > config.maximum_panels:
        raise PerceptionProtocolError('panels', 'too many panel candidates')
    panels = tuple(_panel(item) for item in raw_panels)
    candidate_ids = [panel.candidate_id for panel in panels]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise PerceptionProtocolError('panels', 'panel candidate IDs must be unique')

    dirt_found = _boolean(raw, 'dirt_found')
    dirt_values = {
        name: _normalized(raw, name)
        for name in (
            'dirt_centroid_x_norm',
            'dirt_centroid_y_norm',
            'dirt_bbox_x_norm',
            'dirt_bbox_y_norm',
            'dirt_bbox_w_norm',
            'dirt_bbox_h_norm',
            'dirt_confidence',
            'total_dirty_area_ratio',
            'target_component_area_ratio',
        )
    }
    dirt_component_count = _integer(raw, 'dirt_component_count')
    if dirt_found and min(
        dirt_values['dirt_bbox_w_norm'],
        dirt_values['dirt_bbox_h_norm'],
        dirt_values['dirt_confidence'],
        dirt_values['target_component_area_ratio'],
    ) <= 0.0:
        raise PerceptionProtocolError(
            'dirt_detection', 'dirty result needs a non-empty confident box'
        )
    if not dirt_found and (
        any(dirt_values.values()) or dirt_component_count != 0
    ):
        raise PerceptionProtocolError(
            'dirt_detection', 'clean result must zero all dirt fields'
        )
    panel_visible = _boolean(raw, 'panel_visible')
    target_panel_selected = _boolean(raw, 'target_panel_selected')
    target_panel_candidate_id = _integer(
        raw, 'target_panel_candidate_id', signed=True
    )
    valid = _boolean(raw, 'valid')
    invalid_reason = _string(raw, 'invalid_reason', allow_empty=True)
    active_panel_id = _integer(raw, 'active_panel_id', signed=True)
    if valid and invalid_reason:
        raise PerceptionProtocolError(
            'validity', 'valid packet cannot carry an invalid_reason'
        )
    if not valid and not invalid_reason:
        raise PerceptionProtocolError(
            'validity', 'invalid packet must carry an invalid_reason'
        )
    if panel_visible != bool(panels):
        raise PerceptionProtocolError(
            'panel_visibility', 'panel_visible must match the panel array'
        )
    if target_panel_selected and not panel_visible:
        raise PerceptionProtocolError(
            'panel_selection', 'a selected target requires a visible candidate'
        )
    if target_panel_selected and target_panel_candidate_id not in candidate_ids:
        raise PerceptionProtocolError(
            'panel_selection',
            'selected panel candidate ID must reference the panel array',
        )
    if not target_panel_selected and target_panel_candidate_id != -1:
        raise PerceptionProtocolError(
            'panel_selection',
            'unselected panel candidate ID must be -1',
        )
    if mode == 'clean' and valid and not target_panel_selected:
        raise PerceptionProtocolError(
            'panel_selection', 'valid clean result requires a selected target panel'
        )
    if mode == 'clean' and active_panel_id <= 0:
        raise PerceptionProtocolError(
            'active_panel_id', 'clean mode requires a positive panel ID'
        )
    if dirt_found and (
        mode != 'clean'
        or not valid
        or not panel_visible
        or not target_panel_selected
        or dirt_component_count <= 0
    ):
        raise PerceptionProtocolError(
            'dirt_detection',
            'dirt requires valid clean mode with a visible panel',
        )
    if (
        dirt_values['target_component_area_ratio']
        > dirt_values['total_dirty_area_ratio'] + 1e-6
    ):
        raise PerceptionProtocolError(
            'dirt_detection',
            'target component area cannot exceed total dirty area',
        )
    if (
        dirt_values['dirt_bbox_x_norm'] + dirt_values['dirt_bbox_w_norm']
        > 1.0 + 1e-6
        or dirt_values['dirt_bbox_y_norm']
        + dirt_values['dirt_bbox_h_norm']
        > 1.0 + 1e-6
    ):
        raise PerceptionProtocolError('dirt_detection', 'dirt box exceeds frame')
    if dirt_found and not (
        dirt_values['dirt_bbox_x_norm']
        <= dirt_values['dirt_centroid_x_norm']
        <= dirt_values['dirt_bbox_x_norm'] + dirt_values['dirt_bbox_w_norm']
        and dirt_values['dirt_bbox_y_norm']
        <= dirt_values['dirt_centroid_y_norm']
        <= dirt_values['dirt_bbox_y_norm'] + dirt_values['dirt_bbox_h_norm']
    ):
        raise PerceptionProtocolError(
            'dirt_detection', 'dirt centroid must lie inside the target box'
        )

    inference_time_ms = _number(raw, 'inference_time_ms')
    if not 0.0 <= inference_time_ms <= config.maximum_inference_time_ms:
        raise PerceptionProtocolError(
            'inference_time', 'inference time exceeds receiver policy'
        )
    capture_ns = _integer(raw, 'capture_timestamp_ns')
    inference_ns = _integer(raw, 'inference_timestamp_ns')
    send_ns = _integer(raw, 'send_timestamp_ns')
    if not capture_ns <= inference_ns <= send_ns:
        raise PerceptionProtocolError('timestamp_order', 'timestamps are unordered')
    width = _integer(raw, 'image_width')
    height = _integer(raw, 'image_height')
    if min(width, height) <= 0:
        raise PerceptionProtocolError('image_size', 'image dimensions must be positive')

    return PerceptionPacket(
        protocol_version=version,
        source_id=source_id,
        session_id=_string(raw, 'session_id'),
        frame_id=_integer(raw, 'frame_id'),
        sequence=_integer(raw, 'sequence'),
        capture_timestamp_ns=capture_ns,
        inference_timestamp_ns=inference_ns,
        send_timestamp_ns=send_ns,
        mode=mode,
        image_width=width,
        image_height=height,
        valid=valid,
        panel_visible=panel_visible,
        target_panel_selected=target_panel_selected,
        target_panel_candidate_id=target_panel_candidate_id,
        panels=panels,
        active_panel_id=active_panel_id,
        dirt_found=dirt_found,
        dirt_component_count=dirt_component_count,
        inference_time_ms=inference_time_ms,
        invalid_reason=invalid_reason,
        model_name=_string(raw, 'model_name'),
        model_sha256=_sha256(raw, 'model_sha256'),
        dataset_version=_string(raw, 'dataset_version'),
        **dirt_values,
    )


def _sha256(raw: dict[str, Any], name: str) -> str:
    value = _string(raw, name).lower()
    if len(value) != 64 or any(char not in '0123456789abcdef' for char in value):
        raise PerceptionProtocolError('model_sha256', f'{name} is not SHA-256')
    return value
