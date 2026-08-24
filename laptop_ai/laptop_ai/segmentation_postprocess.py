"""Explicit activation, connected components and deterministic dirt targeting."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

import cv2
import numpy as np

from laptop_ai.preprocessing import LetterboxTransform, inverse_letterbox_map


@dataclass(frozen=True)
class DirtComponent:
    """One accepted connected component in original panel-ROI pixels."""

    component_id: int
    area: int
    area_ratio: float
    centroid_x: float
    centroid_y: float
    bbox_x: int
    bbox_y: int
    bbox_width: int
    bbox_height: int
    confidence: float


@dataclass(frozen=True)
class ComponentSelectionPolicy:
    """Testable weighted policy for choosing the component to spray."""

    area_weight: float = 0.45
    confidence_weight: float = 0.35
    target_distance_weight: float = 0.20

    def __post_init__(self) -> None:
        weights = (
            self.area_weight,
            self.confidence_weight,
            self.target_distance_weight,
        )
        if any(not math.isfinite(value) or value < 0.0 for value in weights):
            raise ValueError('component selection weights must be finite and non-negative')
        if sum(weights) <= 0.0:
            raise ValueError('at least one component selection weight is required')


@dataclass(frozen=True)
class SegmentationResult:
    probability_map: np.ndarray
    binary_mask: np.ndarray
    components: tuple[DirtComponent, ...]
    target: DirtComponent | None
    total_dirty_area_ratio: float

    @property
    def dirt_found(self) -> bool:
        return self.target is not None

    @property
    def component_count(self) -> int:
        return len(self.components)

    @property
    def target_component_area_ratio(self) -> float:
        return self.target.area_ratio if self.target is not None else 0.0


def apply_output_activation(values: np.ndarray, activation: str) -> np.ndarray:
    """Apply only the activation declared by the model manifest."""
    output = np.asarray(values, dtype=np.float32)
    if activation == 'logits':
        return 1.0 / (1.0 + np.exp(-np.clip(output, -30.0, 30.0)))
    if activation == 'probability':
        minimum = float(output.min())
        maximum = float(output.max())
        if minimum < -1e-6 or maximum > 1.0 + 1e-6:
            raise RuntimeError(
                f'probability output is outside [0, 1]: min={minimum}, max={maximum}'
            )
        return np.clip(output, 0.0, 1.0)
    raise RuntimeError(f'unsupported output activation: {activation!r}')


def extract_segmentation_map(
    output: np.ndarray,
    *,
    layout: str,
    output_channel: int,
) -> np.ndarray:
    """Select one binary segmentation channel using an explicit layout."""
    values = np.asarray(output)
    if layout == 'NCHW':
        if values.ndim != 4 or values.shape[0] != 1:
            raise RuntimeError(f'expected NCHW batch size 1, got {values.shape}')
        if not 0 <= output_channel < values.shape[1]:
            raise RuntimeError('output_channel is outside the model output')
        return values[0, output_channel]
    if layout == 'NHW':
        if values.ndim != 3 or values.shape[0] != 1 or output_channel != 0:
            raise RuntimeError(f'expected NHW batch size 1, got {values.shape}')
        return values[0]
    if layout == 'HW':
        if values.ndim != 2 or output_channel != 0:
            raise RuntimeError(f'expected HW output, got {values.shape}')
        return values
    raise RuntimeError(f'unsupported output layout: {layout!r}')


def connected_components(
    probability: np.ndarray,
    *,
    threshold: float,
    minimum_component_area: int,
    minimum_component_area_ratio: float,
) -> tuple[np.ndarray, tuple[DirtComponent, ...]]:
    """Threshold and filter each component independently."""
    values = np.asarray(probability, dtype=np.float32)
    if values.ndim != 2 or values.size == 0:
        raise ValueError('probability map must be a non-empty 2D array')
    if not 0.0 < threshold < 1.0:
        raise ValueError('threshold must be within (0, 1)')
    if minimum_component_area < 0:
        raise ValueError('minimum_component_area cannot be negative')
    if not 0.0 <= minimum_component_area_ratio < 1.0:
        raise ValueError('minimum_component_area_ratio must be within [0, 1)')
    raw_mask = (values >= threshold).astype(np.uint8)
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(
        raw_mask,
        connectivity=8,
    )
    image_area = float(values.shape[0] * values.shape[1])
    accepted_mask = np.zeros_like(raw_mask)
    components = []
    for component_id in range(1, count):
        area = int(stats[component_id, cv2.CC_STAT_AREA])
        area_ratio = area / image_area
        if area < minimum_component_area or area_ratio < minimum_component_area_ratio:
            continue
        component_pixels = labels == component_id
        accepted_mask[component_pixels] = 1
        components.append(
            DirtComponent(
                component_id=component_id,
                area=area,
                area_ratio=area_ratio,
                centroid_x=float(centroids[component_id, 0]),
                centroid_y=float(centroids[component_id, 1]),
                bbox_x=int(stats[component_id, cv2.CC_STAT_LEFT]),
                bbox_y=int(stats[component_id, cv2.CC_STAT_TOP]),
                bbox_width=int(stats[component_id, cv2.CC_STAT_WIDTH]),
                bbox_height=int(stats[component_id, cv2.CC_STAT_HEIGHT]),
                confidence=float(values[component_pixels].mean()),
            )
        )
    return accepted_mask, tuple(components)


def select_target_component(
    components: Sequence[DirtComponent],
    *,
    image_width: int,
    image_height: int,
    target_x_norm: float,
    target_y_norm: float,
    policy: ComponentSelectionPolicy,
) -> DirtComponent | None:
    """Select highest weighted area/confidence/proximity score deterministically."""
    if not components:
        return None
    if min(image_width, image_height) <= 0:
        raise ValueError('image dimensions must be positive')
    if not 0.0 <= target_x_norm <= 1.0 or not 0.0 <= target_y_norm <= 1.0:
        raise ValueError('target coordinates must be normalized')
    maximum_area = max(component.area_ratio for component in components)
    denominator = policy.area_weight + policy.confidence_weight + policy.target_distance_weight

    def key(component: DirtComponent) -> tuple[float, int]:
        x_norm = component.centroid_x / image_width
        y_norm = component.centroid_y / image_height
        distance_score = 1.0 - min(
            1.0,
            math.hypot(x_norm - target_x_norm, y_norm - target_y_norm) / math.sqrt(2.0),
        )
        score = (
            policy.area_weight * component.area_ratio / maximum_area
            + policy.confidence_weight * component.confidence
            + policy.target_distance_weight * distance_score
        ) / denominator
        return score, -component.component_id

    return max(components, key=key)


def postprocess_segmentation(
    output: np.ndarray,
    transform: LetterboxTransform,
    *,
    activation: str,
    output_layout: str,
    output_channel: int,
    threshold: float,
    minimum_component_area: int,
    minimum_component_area_ratio: float,
    target_x_norm: float = 0.5,
    target_y_norm: float = 0.5,
    selection_policy: ComponentSelectionPolicy | None = None,
) -> SegmentationResult:
    """Map output to the original ROI, filter components and choose a target."""
    model_map = extract_segmentation_map(
        output,
        layout=output_layout,
        output_channel=output_channel,
    )
    model_probability = apply_output_activation(model_map, activation)
    probability = inverse_letterbox_map(model_probability, transform)
    mask, components = connected_components(
        probability,
        threshold=threshold,
        minimum_component_area=minimum_component_area,
        minimum_component_area_ratio=minimum_component_area_ratio,
    )
    target = select_target_component(
        components,
        image_width=transform.original_width,
        image_height=transform.original_height,
        target_x_norm=target_x_norm,
        target_y_norm=target_y_norm,
        policy=selection_policy or ComponentSelectionPolicy(),
    )
    return SegmentationResult(
        probability_map=probability,
        binary_mask=mask,
        components=components,
        target=target,
        total_dirty_area_ratio=float(mask.mean()),
    )
