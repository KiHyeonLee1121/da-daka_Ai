"""Model-specific ONNX output conversion kept outside the runtime wrapper."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class OnnxCandidate:
    centroid: tuple[float, float]
    bbox: tuple[float, float, float, float]
    area: float
    confidence: float


def postprocess_xyxy_score_class(
    output: Any,
    *,
    image_width: int,
    image_height: int,
    input_width: int,
    input_height: int,
    confidence_threshold: float,
    class_id: int,
    coordinates_normalized: bool,
) -> OnnxCandidate | None:
    """Read rows shaped [x1, y1, x2, y2, score, class_id]."""
    rows = np.asarray(output)
    rows = np.squeeze(rows)
    if rows.ndim == 1:
        rows = rows.reshape(1, -1)
    if rows.ndim != 2:
        raise ValueError(f"unsupported ONNX output rank/shape: {rows.shape}")
    if rows.shape[1] != 6 and rows.shape[0] == 6:
        rows = rows.T
    if rows.shape[1] < 6:
        raise ValueError(
            "ONNX output must contain rows [x1,y1,x2,y2,score,class_id]; "
            f"got {rows.shape}"
        )

    best: OnnxCandidate | None = None
    for row in rows:
        values = [float(value) for value in row[:6]]
        if not all(np.isfinite(values)):
            continue
        x1, y1, x2, y2, confidence, candidate_class = values
        if int(round(candidate_class)) != class_id or confidence < confidence_threshold:
            continue
        if coordinates_normalized:
            x1 *= image_width
            x2 *= image_width
            y1 *= image_height
            y2 *= image_height
        else:
            x1 *= image_width / input_width
            x2 *= image_width / input_width
            y1 *= image_height / input_height
            y2 *= image_height / input_height
        x1 = min(max(x1, 0.0), float(image_width))
        x2 = min(max(x2, 0.0), float(image_width))
        y1 = min(max(y1, 0.0), float(image_height))
        y2 = min(max(y2, 0.0), float(image_height))
        width = x2 - x1
        height = y2 - y1
        if width <= 0.0 or height <= 0.0:
            continue
        candidate = OnnxCandidate(
            centroid=(x1 + width / 2.0, y1 + height / 2.0),
            bbox=(x1, y1, width, height),
            area=width * height,
            confidence=confidence,
        )
        if best is None or candidate.confidence > best.confidence:
            best = candidate
    return best
