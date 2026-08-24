"""Build complete Pi perception-protocol-v3 JSON payloads."""

import json


ZERO_DIRT = {
    'dirt_centroid_x_norm': 0.0,
    'dirt_centroid_y_norm': 0.0,
    'dirt_bbox_x_norm': 0.0,
    'dirt_bbox_y_norm': 0.0,
    'dirt_bbox_w_norm': 0.0,
    'dirt_bbox_h_norm': 0.0,
    'dirt_confidence': 0.0,
    'total_dirty_area_ratio': 0.0,
    'dirt_component_count': 0,
    'target_component_area_ratio': 0.0,
}


def encode_result(**values) -> bytes:
    """Serialize one result using compact UTF-8 JSON."""
    payload = {'protocol_version': 3, **values}
    return json.dumps(payload, separators=(',', ':'), allow_nan=False).encode(
        'utf-8'
    )
