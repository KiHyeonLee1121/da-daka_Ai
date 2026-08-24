"""Configurable iPhone-to-IMX708 domain augmentation for training only."""

from __future__ import annotations

import cv2
import numpy as np


def augment_image_mask(
    image: np.ndarray,
    mask: np.ndarray | None,
    config: dict,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Apply bounded photometric and synchronized geometric transforms."""
    output = image.copy()
    target = None if mask is None else mask.copy()
    height, width = output.shape[:2]

    if _chance(rng, config, 'brightness_probability'):
        limit = float(config.get('brightness_limit', 0.18))
        output = np.clip(
            output.astype(np.float32) * rng.uniform(1.0 - limit, 1.0 + limit),
            0,
            255,
        ).astype(np.uint8)
    if _chance(rng, config, 'color_probability'):
        gains = rng.uniform(0.90, 1.10, size=(1, 1, 3))
        output = np.clip(output.astype(np.float32) * gains, 0, 255).astype(np.uint8)
    if _chance(rng, config, 'shadow_probability'):
        overlay = np.ones((height, width), dtype=np.float32)
        x1, x2 = sorted(rng.integers(-width // 2, width + width // 2, size=2))
        polygon = np.asarray(
            [[x1, 0], [x2, 0], [x2 + width // 3, height], [x1 + width // 3, height]],
            dtype=np.int32,
        )
        cv2.fillPoly(overlay, [polygon], float(rng.uniform(0.55, 0.85)))
        output = np.clip(
            output.astype(np.float32) * overlay[..., None], 0, 255
        ).astype(np.uint8)
    if _chance(rng, config, 'specular_probability'):
        center = (int(rng.integers(0, width)), int(rng.integers(0, height)))
        axes = (
            max(3, int(width * rng.uniform(0.03, 0.12))),
            max(3, int(height * rng.uniform(0.02, 0.08))),
        )
        glare = output.copy()
        cv2.ellipse(
            glare, center, axes, float(rng.uniform(0, 180)),
            0, 360, (255, 255, 255), -1,
        )
        output = cv2.addWeighted(output, 0.72, glare, 0.28, 0.0)
    if _chance(rng, config, 'motion_blur_probability'):
        kernel_size = int(rng.choice([3, 5, 7]))
        kernel = np.zeros((kernel_size, kernel_size), dtype=np.float32)
        if rng.random() < 0.5:
            kernel[kernel_size // 2, :] = 1.0 / kernel_size
        else:
            kernel[:, kernel_size // 2] = 1.0 / kernel_size
        output = cv2.filter2D(output, -1, kernel)
    if _chance(rng, config, 'defocus_blur_probability'):
        kernel_size = int(rng.choice([3, 5]))
        output = cv2.GaussianBlur(output, (kernel_size, kernel_size), 0)
    if _chance(rng, config, 'noise_probability'):
        sigma = float(rng.uniform(2.0, float(config.get('noise_sigma_max', 10.0))))
        noise = rng.normal(0.0, sigma, size=output.shape)
        output = np.clip(output.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    if _chance(rng, config, 'compression_probability'):
        quality = int(rng.integers(int(config.get('jpeg_quality_min', 60)), 96))
        ok, encoded = cv2.imencode('.jpg', output, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if ok:
            output = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if target is not None and _chance(rng, config, 'perspective_probability'):
        magnitude = float(config.get('perspective_limit', 0.035))
        source = np.asarray(
            [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
            dtype=np.float32,
        )
        offsets = rng.uniform(-magnitude, magnitude, size=(4, 2)).astype(np.float32)
        offsets[:, 0] *= width
        offsets[:, 1] *= height
        matrix = cv2.getPerspectiveTransform(source, source + offsets)
        output = cv2.warpPerspective(
            output, matrix, (width, height), flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT_101,
        )
        target = cv2.warpPerspective(
            target, matrix, (width, height), flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT, borderValue=0,
        )
    if target is not None and _chance(rng, config, 'scale_probability'):
        limit = float(config.get('scale_limit', 0.08))
        scale = float(rng.uniform(1.0 - limit, 1.0 + limit))
        matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), 0.0, scale)
        output = cv2.warpAffine(
            output, matrix, (width, height), flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT_101,
        )
        target = cv2.warpAffine(
            target, matrix, (width, height), flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT, borderValue=0,
        )
    return output, target


def _chance(rng, config, name):
    probability = float(config.get(name, 0.0))
    if not 0.0 <= probability <= 1.0:
        raise ValueError(f'{name} must be within [0, 1]')
    return rng.random() < probability
