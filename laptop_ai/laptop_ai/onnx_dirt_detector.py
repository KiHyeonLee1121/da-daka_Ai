"""Manifest-validated ONNX segmentation for one aspect-safe panel ROI."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import onnxruntime as ort

from laptop_ai.model_contract import ModelManifest
from laptop_ai.preprocessing import preprocess_bgr
from laptop_ai.runtime_tuning import (
    RuntimeTuning,
    configure_cuda_environment,
    create_session_options,
    cuda_provider,
)
from laptop_ai.segmentation_postprocess import (
    ComponentSelectionPolicy,
    DirtComponent,
    postprocess_segmentation,
)


@dataclass(frozen=True)
class DirtMaskResult:
    """Target and aggregate component information in panel-ROI coordinates."""

    centroid_x_norm: float
    centroid_y_norm: float
    bbox_x_norm: float
    bbox_y_norm: float
    bbox_w_norm: float
    bbox_h_norm: float
    confidence: float
    total_dirty_area_ratio: float
    component_count: int
    target_component_area_ratio: float
    components: tuple[DirtComponent, ...]


class OnnxDirtSegmenter:
    """Run a bundle whose manifest and ONNX metadata agree exactly."""

    def __init__(
        self,
        manifest_path: str,
        *,
        backend: str = 'cuda',
        performance: dict | None = None,
    ) -> None:
        self.manifest = ModelManifest.load(
            manifest_path,
            expected_task='dirt_segmentation',
        )
        backend = backend.lower()
        if backend not in {'cuda', 'cpu'}:
            raise ValueError('ONNX backend must be cuda or cpu')
        self.tuning = RuntimeTuning.from_mapping(performance)
        providers = ort.get_available_providers()
        if backend == 'cuda':
            if 'CUDAExecutionProvider' not in providers:
                raise RuntimeError(
                    'onnxruntime-gpu CUDAExecutionProvider is unavailable; '
                    f'providers={providers}'
                )
            configure_cuda_environment(self.tuning)
            requested_providers = [
                cuda_provider(self.tuning),
                'CPUExecutionProvider',
            ]
        else:
            if 'CPUExecutionProvider' not in providers:
                raise RuntimeError('ONNX CPUExecutionProvider is unavailable')
            requested_providers = ['CPUExecutionProvider']
        self.session = ort.InferenceSession(
            str(self.manifest.model_path),
            sess_options=create_session_options(ort, self.tuning),
            providers=requested_providers,
        )
        active = self.session.get_providers()[0]
        expected = (
            'CUDAExecutionProvider' if backend == 'cuda'
            else 'CPUExecutionProvider'
        )
        if active != expected:
            raise RuntimeError(
                f'ONNX Runtime activated {active}, expected {expected}'
            )
        self.manifest.verify_onnx_session(self.session)
        self.input_name = self.session.get_inputs()[0].name
        self.model_name = self.manifest.model_file
        self.model_sha256 = self.manifest.model_sha256
        self.dataset_version = self.manifest.dataset_version
        self._warmup_remaining = self.tuning.onnx_warmup_runs

        raw = self.manifest.raw
        self.minimum_component_area = int(raw['minimum_component_area'])
        self.minimum_component_area_ratio = float(
            raw['minimum_component_area_ratio']
        )
        if self.minimum_component_area < 0:
            raise ValueError('minimum_component_area cannot be negative')
        if not 0.0 <= self.minimum_component_area_ratio < 1.0:
            raise ValueError(
                'minimum_component_area_ratio must be within [0, 1)'
            )
        policy = raw['target_selection']
        if not isinstance(policy, dict):
            raise ValueError('target_selection must be an object')
        self.selection_policy = ComponentSelectionPolicy(
            area_weight=float(policy['area_weight']),
            confidence_weight=float(policy['confidence_weight']),
            target_distance_weight=float(
                policy['target_distance_weight']
            ),
        )

    def detect(
        self,
        bgr_roi: np.ndarray,
        *,
        target_x_norm: float = 0.5,
        target_y_norm: float = 0.5,
    ) -> DirtMaskResult | None:
        """Return the selected component and aggregate accepted-mask values."""
        if bgr_roi is None or bgr_roi.size == 0:
            raise ValueError('non-empty panel ROI is required')
        tensor, transform = preprocess_bgr(bgr_roi, self.manifest)
        while self._warmup_remaining > 0:
            self.session.run(None, {self.input_name: tensor})
            self._warmup_remaining -= 1
        outputs = self.session.run(None, {self.input_name: tensor})
        if len(outputs) != 1:
            raise RuntimeError(
                'segmentation model returned an unexpected output count'
            )
        result = postprocess_segmentation(
            outputs[0],
            transform,
            activation=self.manifest.output_activation,
            output_layout=self.manifest.output_layout,
            output_channel=self.manifest.output_channel,
            threshold=self.manifest.threshold,
            minimum_component_area=self.minimum_component_area,
            minimum_component_area_ratio=self.minimum_component_area_ratio,
            target_x_norm=target_x_norm,
            target_y_norm=target_y_norm,
            selection_policy=self.selection_policy,
        )
        target = result.target
        if target is None:
            return None
        height, width = bgr_roi.shape[:2]
        return DirtMaskResult(
            centroid_x_norm=float(target.centroid_x / width),
            centroid_y_norm=float(target.centroid_y / height),
            bbox_x_norm=float(target.bbox_x / width),
            bbox_y_norm=float(target.bbox_y / height),
            bbox_w_norm=float(target.bbox_width / width),
            bbox_h_norm=float(target.bbox_height / height),
            confidence=target.confidence,
            total_dirty_area_ratio=result.total_dirty_area_ratio,
            component_count=result.component_count,
            target_component_area_ratio=result.target_component_area_ratio,
            components=result.components,
        )
