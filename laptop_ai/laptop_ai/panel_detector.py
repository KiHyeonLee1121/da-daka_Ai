"""Learned production and classical diagnostic panel detectors."""

from dataclasses import dataclass
import math

import cv2
import numpy as np


@dataclass(frozen=True)
class PanelRectangle:
    candidate_id: int
    x: int
    y: int
    width: int
    height: int
    confidence: float

    def normalized(self, image_width: int, image_height: int) -> dict:
        return {
            'candidate_id': self.candidate_id,
            'center_x_norm': (self.x + self.width / 2.0) / image_width,
            'center_y_norm': (self.y + self.height / 2.0) / image_height,
            'width_norm': self.width / image_width,
            'height_norm': self.height / image_height,
            'confidence': self.confidence,
        }


def select_panel_nearest_target(
    panels: list[PanelRectangle],
    *,
    image_width: int,
    image_height: int,
    target_x_norm: float,
    target_y_norm: float,
    maximum_distance_norm: float,
) -> PanelRectangle | None:
    """Select the panel nearest the expected camera/nozzle target point."""
    values = (target_x_norm, target_y_norm, maximum_distance_norm)
    if not all(math.isfinite(value) for value in values):
        raise ValueError('panel target selection values must be finite')
    if min(image_width, image_height) <= 0:
        raise ValueError('image dimensions must be positive')
    if not 0.0 <= target_x_norm <= 1.0 or not 0.0 <= target_y_norm <= 1.0:
        raise ValueError('panel target point must be normalized')
    if not 0.0 < maximum_distance_norm <= math.sqrt(2.0):
        raise ValueError('maximum panel target distance is invalid')
    if not panels:
        return None

    def score(panel: PanelRectangle) -> tuple[float, float, int]:
        center_x = (panel.x + panel.width / 2.0) / image_width
        center_y = (panel.y + panel.height / 2.0) / image_height
        distance = math.hypot(
            center_x - target_x_norm,
            center_y - target_y_norm,
        )
        return distance, -panel.confidence, panel.candidate_id

    selected = min(panels, key=score)
    return selected if score(selected)[0] <= maximum_distance_norm else None


class PanelDetector:
    """Classical contour detector retained for diagnostics and comparison."""

    def __init__(
        self,
        *,
        minimum_area_ratio: float,
        maximum_area_ratio: float,
        minimum_aspect_ratio: float,
        maximum_aspect_ratio: float,
        maximum_panels: int,
    ) -> None:
        if not 0.0 < minimum_area_ratio < maximum_area_ratio <= 1.0:
            raise ValueError('panel area ratio bounds are invalid')
        if not 0.0 < minimum_aspect_ratio < maximum_aspect_ratio:
            raise ValueError('panel aspect ratio bounds are invalid')
        if maximum_panels <= 0:
            raise ValueError('maximum_panels must be positive')
        self.minimum_area_ratio = minimum_area_ratio
        self.maximum_area_ratio = maximum_area_ratio
        self.minimum_aspect_ratio = minimum_aspect_ratio
        self.maximum_aspect_ratio = maximum_aspect_ratio
        self.maximum_panels = maximum_panels

    def detect(self, frame: np.ndarray) -> list[PanelRectangle]:
        if frame is None or frame.ndim != 3:
            raise ValueError('BGR frame is required')
        height, width = frame.shape[:2]
        frame_area = float(width * height)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 60, 160)
        edges = cv2.morphologyEx(
            edges,
            cv2.MORPH_CLOSE,
            np.ones((5, 5), dtype=np.uint8),
        )
        contours, _hierarchy = cv2.findContours(
            edges,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        candidates = []
        for contour in contours:
            area = float(cv2.contourArea(contour))
            area_ratio = area / frame_area
            if not self.minimum_area_ratio <= area_ratio <= self.maximum_area_ratio:
                continue
            perimeter = cv2.arcLength(contour, True)
            polygon = cv2.approxPolyDP(contour, 0.03 * perimeter, True)
            if len(polygon) != 4 or not cv2.isContourConvex(polygon):
                continue
            x, y, box_width, box_height = cv2.boundingRect(polygon)
            if min(box_width, box_height) <= 0:
                continue
            aspect = max(box_width, box_height) / min(box_width, box_height)
            if not self.minimum_aspect_ratio <= aspect <= self.maximum_aspect_ratio:
                continue
            rectangularity = min(1.0, area / float(box_width * box_height))
            confidence = max(0.01, min(1.0, rectangularity))
            candidates.append((area, x, y, box_width, box_height, confidence))
        candidates.sort(key=lambda value: (-value[0], value[1], value[2]))
        return [
            PanelRectangle(index, x, y, box_width, box_height, confidence)
            for index, (_area, x, y, box_width, box_height, confidence)
            in enumerate(candidates[:self.maximum_panels], 1)
        ]


class OnnxPanelDetector:
    """Manifest-validated learned solar-panel detector for production use."""

    def __init__(
        self,
        manifest_path: str,
        *,
        backend: str = 'cuda',
        performance: dict | None = None,
    ) -> None:
        import onnxruntime as ort

        from laptop_ai.model_contract import ModelContractError, ModelManifest
        from laptop_ai.runtime_tuning import (
            RuntimeTuning,
            configure_cuda_environment,
            create_session_options,
            cuda_provider,
        )

        self.manifest = ModelManifest.load(
            manifest_path,
            expected_task='panel_detection',
        )
        output_names = self.manifest.raw.get('output_names')
        if output_names != ['boxes', 'scores', 'labels']:
            raise ModelContractError(
                'panel output_names must be ["boxes", "scores", "labels"]'
            )
        coordinates = self.manifest.raw['box_coordinates']
        if coordinates not in {'input_pixels', 'input_normalized'}:
            raise ModelContractError(
                'box_coordinates must be input_pixels or input_normalized'
            )
        self.box_coordinates = coordinates
        self.panel_label_id = int(self.manifest.raw['panel_label_id'])
        self.maximum_panels = int(self.manifest.raw['maximum_detections'])
        self.nms_iou_threshold = float(
            self.manifest.raw['nms_iou_threshold']
        )
        if self.panel_label_id < 0 or self.maximum_panels <= 0:
            raise ModelContractError('invalid panel detector label/count contract')
        if not 0.0 < self.nms_iou_threshold < 1.0:
            raise ModelContractError('nms_iou_threshold must be within (0, 1)')

        backend = backend.lower()
        if backend not in {'cuda', 'cpu'}:
            raise ValueError('ONNX backend must be cuda or cpu')
        tuning = RuntimeTuning.from_mapping(performance)
        available = ort.get_available_providers()
        if backend == 'cuda':
            if 'CUDAExecutionProvider' not in available:
                raise RuntimeError(
                    'panel detector requires CUDAExecutionProvider; '
                    f'providers={available}'
                )
            configure_cuda_environment(tuning)
            providers = [cuda_provider(tuning), 'CPUExecutionProvider']
        else:
            providers = ['CPUExecutionProvider']
        self.session = ort.InferenceSession(
            str(self.manifest.model_path),
            sess_options=create_session_options(ort, tuning),
            providers=providers,
        )
        expected_provider = (
            'CUDAExecutionProvider' if backend == 'cuda'
            else 'CPUExecutionProvider'
        )
        if self.session.get_providers()[0] != expected_provider:
            raise RuntimeError('ONNX panel detector did not activate requested backend')
        self.manifest.verify_onnx_session(self.session)
        self.input_name = self.session.get_inputs()[0].name
        self.model_name = self.manifest.model_file

    def detect(self, frame: np.ndarray) -> list[PanelRectangle]:
        """Return model boxes mapped exactly back to full-frame pixels."""
        from laptop_ai.preprocessing import preprocess_bgr

        if frame is None or frame.ndim != 3 or frame.size == 0:
            raise ValueError('BGR frame is required')
        tensor, transform = preprocess_bgr(frame, self.manifest)
        output = self.session.run(
            ['boxes', 'scores', 'labels'],
            {self.input_name: tensor},
        )
        boxes = np.asarray(output[0], dtype=np.float32)
        scores = np.asarray(output[1], dtype=np.float32).reshape(-1)
        labels = np.asarray(output[2]).reshape(-1)
        if boxes.ndim == 3 and boxes.shape[0] == 1:
            boxes = boxes[0]
        if boxes.ndim != 2 or boxes.shape[1] != 4:
            raise RuntimeError(f'panel boxes must have shape [N,4], got {boxes.shape}')
        if not len(boxes) == len(scores) == len(labels):
            raise RuntimeError('panel output lengths do not match')
        candidates: list[tuple[float, tuple[float, float, float, float]]] = []
        for box, score, label in zip(boxes, scores, labels):
            confidence = float(score)
            if int(label) != self.panel_label_id or confidence < self.manifest.threshold:
                continue
            x1, y1, x2, y2 = (float(value) for value in box)
            if self.box_coordinates == 'input_normalized':
                x1 *= self.manifest.input_width
                x2 *= self.manifest.input_width
                y1 *= self.manifest.input_height
                y2 *= self.manifest.input_height
            x, y, width, height = transform.to_original_bbox(
                (x1, y1, x2 - x1, y2 - y1)
            )
            if min(width, height) <= 1.0:
                continue
            candidates.append((confidence, (x, y, width, height)))
        kept = _nms(candidates, self.nms_iou_threshold)
        kept.sort(key=lambda item: (-item[0], item[1][0], item[1][1]))
        result = []
        frame_height, frame_width = frame.shape[:2]
        for index, (confidence, box) in enumerate(
            kept[:self.maximum_panels],
            1,
        ):
            x, y, width, height = box
            left = max(0, min(frame_width - 1, int(round(x))))
            top = max(0, min(frame_height - 1, int(round(y))))
            right = max(left + 1, min(frame_width, int(round(x + width))))
            bottom = max(top + 1, min(frame_height, int(round(y + height))))
            result.append(
                PanelRectangle(
                    index,
                    left,
                    top,
                    right - left,
                    bottom - top,
                    confidence,
                )
            )
        return result


def _nms(
    candidates: list[tuple[float, tuple[float, float, float, float]]],
    iou_threshold: float,
) -> list[tuple[float, tuple[float, float, float, float]]]:
    """Small deterministic NMS used for the explicit three-output contract."""
    ordered = sorted(candidates, key=lambda item: -item[0])
    kept = []
    while ordered:
        chosen = ordered.pop(0)
        kept.append(chosen)
        ordered = [
            item for item in ordered
            if _bbox_iou(chosen[1], item[1]) <= iou_threshold
        ]
    return kept


def _bbox_iou(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    intersection_width = max(0.0, min(lx + lw, rx + rw) - max(lx, rx))
    intersection_height = max(0.0, min(ly + lh, ry + rh) - max(ly, ry))
    intersection = intersection_width * intersection_height
    union = lw * lh + rw * rh - intersection
    return intersection / union if union > 0.0 else 0.0
