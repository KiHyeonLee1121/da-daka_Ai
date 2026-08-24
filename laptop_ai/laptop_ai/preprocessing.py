"""Aspect-ratio-safe preprocessing and invertible coordinate transforms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import cv2
import numpy as np


@dataclass(frozen=True)
class LetterboxTransform:
    """Geometry used to map an original image to one padded model input."""

    original_width: int
    original_height: int
    input_width: int
    input_height: int
    resized_width: int
    resized_height: int
    pad_left: int
    pad_top: int
    pad_right: int
    pad_bottom: int
    scale: float

    def to_input_points(self, points: np.ndarray) -> np.ndarray:
        values = np.asarray(points, dtype=np.float32).copy()
        values[..., 0] = values[..., 0] * self.scale + self.pad_left
        values[..., 1] = values[..., 1] * self.scale + self.pad_top
        return values

    def to_original_points(self, points: np.ndarray) -> np.ndarray:
        values = np.asarray(points, dtype=np.float32).copy()
        values[..., 0] = (values[..., 0] - self.pad_left) / self.scale
        values[..., 1] = (values[..., 1] - self.pad_top) / self.scale
        values[..., 0] = np.clip(values[..., 0], 0.0, self.original_width)
        values[..., 1] = np.clip(values[..., 1], 0.0, self.original_height)
        return values

    def to_input_bbox(self, bbox: Iterable[float]) -> tuple[float, float, float, float]:
        x, y, width, height = (float(value) for value in bbox)
        points = self.to_input_points(
            np.asarray([[x, y], [x + width, y + height]], dtype=np.float32)
        )
        return (
            float(points[0, 0]),
            float(points[0, 1]),
            float(points[1, 0] - points[0, 0]),
            float(points[1, 1] - points[0, 1]),
        )

    def to_original_bbox(self, bbox: Iterable[float]) -> tuple[float, float, float, float]:
        x, y, width, height = (float(value) for value in bbox)
        points = self.to_original_points(
            np.asarray([[x, y], [x + width, y + height]], dtype=np.float32)
        )
        return (
            float(points[0, 0]),
            float(points[0, 1]),
            float(max(0.0, points[1, 0] - points[0, 0])),
            float(max(0.0, points[1, 1] - points[0, 1])),
        )


def compute_letterbox_transform(
    original_width: int,
    original_height: int,
    input_width: int,
    input_height: int,
) -> LetterboxTransform:
    """Compute deterministic centered padding with no aspect-ratio distortion."""
    if min(original_width, original_height, input_width, input_height) <= 0:
        raise ValueError('letterbox dimensions must be positive')
    scale = min(input_width / original_width, input_height / original_height)
    resized_width = min(input_width, max(1, int(round(original_width * scale))))
    resized_height = min(input_height, max(1, int(round(original_height * scale))))
    remaining_x = input_width - resized_width
    remaining_y = input_height - resized_height
    pad_left = remaining_x // 2
    pad_top = remaining_y // 2
    return LetterboxTransform(
        original_width=original_width,
        original_height=original_height,
        input_width=input_width,
        input_height=input_height,
        resized_width=resized_width,
        resized_height=resized_height,
        pad_left=pad_left,
        pad_top=pad_top,
        pad_right=remaining_x - pad_left,
        pad_bottom=remaining_y - pad_top,
        scale=scale,
    )


def letterbox_image(
    image: np.ndarray,
    input_width: int,
    input_height: int,
    *,
    padding_value: int = 114,
    interpolation: int = cv2.INTER_LINEAR,
) -> tuple[np.ndarray, LetterboxTransform]:
    """Resize one image with preserved aspect ratio and centered padding."""
    if image is None or image.ndim not in {2, 3} or image.size == 0:
        raise ValueError('a non-empty image is required')
    height, width = image.shape[:2]
    transform = compute_letterbox_transform(width, height, input_width, input_height)
    resized = cv2.resize(
        image,
        (transform.resized_width, transform.resized_height),
        interpolation=interpolation,
    )
    if image.ndim == 2:
        output = np.full((input_height, input_width), padding_value, dtype=image.dtype)
    else:
        output = np.full(
            (input_height, input_width, image.shape[2]),
            padding_value,
            dtype=image.dtype,
        )
    top = transform.pad_top
    left = transform.pad_left
    output[
        top:top + transform.resized_height,
        left:left + transform.resized_width,
    ] = resized
    return output, transform


def preprocess_bgr(image: np.ndarray, manifest) -> tuple[np.ndarray, LetterboxTransform]:
    """Apply the manifest color, normalization and NCHW input contract."""
    padded, transform = letterbox_image(
        image,
        manifest.input_width,
        manifest.input_height,
        padding_value=manifest.padding_value,
    )
    if manifest.color == 'RGB':
        padded = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
    values = padded.astype(np.float32) * manifest.scale
    mean = np.asarray(manifest.mean, dtype=np.float32).reshape(1, 1, 3)
    std = np.asarray(manifest.std, dtype=np.float32).reshape(1, 1, 3)
    values = (values - mean) / std
    return np.ascontiguousarray(values.transpose(2, 0, 1)[None]), transform


def inverse_letterbox_map(
    model_map: np.ndarray,
    transform: LetterboxTransform,
    *,
    interpolation: int = cv2.INTER_LINEAR,
) -> np.ndarray:
    """Remove padding and map a model-space raster to original coordinates."""
    values = np.asarray(model_map)
    if values.ndim != 2:
        raise ValueError('model map must be two-dimensional')
    if values.shape != (transform.input_height, transform.input_width):
        values = cv2.resize(
            values,
            (transform.input_width, transform.input_height),
            interpolation=interpolation,
        )
    top = transform.pad_top
    left = transform.pad_left
    cropped = values[
        top:top + transform.resized_height,
        left:left + transform.resized_width,
    ]
    return cv2.resize(
        cropped,
        (transform.original_width, transform.original_height),
        interpolation=interpolation,
    )
