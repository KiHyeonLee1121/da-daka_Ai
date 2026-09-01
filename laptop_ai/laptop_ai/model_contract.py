"""Fail-closed model bundle contract shared by training and inference."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SUPPORTED_TASKS = {'panel_detection', 'dirt_segmentation'}


class ModelContractError(RuntimeError):
    """A model artifact does not match its declared production contract."""


def sha256_file(path: str | Path) -> str:
    """Return the lowercase SHA-256 of one file without loading it at once."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def verify_pipeline_dataset_identity(*manifests: 'ModelManifest') -> None:
    """Require all cooperating models to declare the same Master Dataset."""
    identities = {
        (manifest.dataset_version, manifest.dataset_fingerprint)
        for manifest in manifests
    }
    if len(identities) != 1:
        raise ModelContractError(
            'pipeline model dataset version/fingerprint mismatch: '
            f'{sorted(identities)}'
        )


def _integer(raw: Mapping[str, Any], name: str, *, minimum: int = 1) -> int:
    value = raw.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ModelContractError(f'{name} must be an integer >= {minimum}')
    return value


def _number(raw: Mapping[str, Any], name: str) -> float:
    value = raw.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelContractError(f'{name} must be numeric')
    result = float(value)
    if not result == result or result in {float('inf'), -float('inf')}:
        raise ModelContractError(f'{name} must be finite')
    return result


def _vector(raw: Mapping[str, Any], name: str, length: int) -> tuple[float, ...]:
    value = raw.get(name)
    if not isinstance(value, list) or len(value) != length:
        raise ModelContractError(f'{name} must contain {length} numbers')
    mapped = {str(index): item for index, item in enumerate(value)}
    return tuple(_number(mapped, str(index)) for index in range(length))


@dataclass(frozen=True)
class ModelManifest:
    """Validated metadata that makes model preprocessing explicit."""

    path: Path
    raw: Mapping[str, Any]
    manifest_version: int
    task: str
    model_file: str
    model_sha256: str
    onnx_opset: int
    checkpoint_sha256: str
    input_width: int
    input_height: int
    resize: str
    padding_value: int
    color: str
    dtype: str
    channel_order: str
    scale: float
    mean: tuple[float, float, float]
    std: tuple[float, float, float]
    output_activation: str
    output_layout: str
    output_channel: int
    threshold: float
    dataset_version: str
    dataset_fingerprint: str
    git_commit: str

    @property
    def model_path(self) -> Path:
        return self.path.parent / self.model_file

    @property
    def input_shape(self) -> tuple[int, int, int, int]:
        return (1, 3, self.input_height, self.input_width)

    @classmethod
    def load(
        cls,
        manifest_path: str | Path,
        *,
        expected_task: str | None = None,
        verify_model_hash: bool = True,
    ) -> 'ModelManifest':
        path = Path(manifest_path).expanduser().resolve()
        if not path.is_file():
            raise ModelContractError(f'model manifest does not exist: {path}')
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelContractError(f'invalid model manifest: {exc}') from exc
        if not isinstance(raw, dict):
            raise ModelContractError('model manifest must be a JSON object')
        if raw.get('manifest_version') != 1:
            raise ModelContractError('only model manifest_version 1 is supported')

        task = raw.get('task')
        if task not in SUPPORTED_TASKS:
            raise ModelContractError(f'unsupported model task: {task!r}')
        if expected_task is not None and task != expected_task:
            raise ModelContractError(
                f'expected task {expected_task!r}, manifest declares {task!r}'
            )
        activation = str(raw.get('output_activation', '')).lower()
        if task == 'dirt_segmentation' and activation not in {
            'logits',
            'probability',
        }:
            raise ModelContractError(
                'dirt output_activation must be explicitly logits or probability'
            )
        if task == 'panel_detection' and activation != 'none':
            raise ModelContractError('panel detector output_activation must be none')

        resize = str(raw.get('resize', '')).lower()
        if resize != 'letterbox':
            raise ModelContractError('resize must be letterbox')
        color = str(raw.get('color', '')).upper()
        if color not in {'RGB', 'BGR'}:
            raise ModelContractError('color must be RGB or BGR')
        dtype = str(raw.get('dtype', '')).lower()
        if dtype != 'float32':
            raise ModelContractError('only float32 model input is supported')
        channel_order = str(raw.get('channel_order', '')).upper()
        if channel_order != 'NCHW':
            raise ModelContractError('channel_order must be NCHW')
        output_layout = str(raw.get('output_layout', 'NCHW')).upper()
        if output_layout not in {'NCHW', 'NHW', 'HW'}:
            raise ModelContractError('unsupported output_layout')

        output_names = raw.get('output_names')
        if (
            not isinstance(output_names, list)
            or not output_names
            or not all(isinstance(item, str) and item for item in output_names)
        ):
            raise ModelContractError('output_names must be a non-empty string list')
        if task == 'dirt_segmentation':
            output_shape = raw.get('output_shape')
            if not isinstance(output_shape, list) or not output_shape:
                raise ModelContractError('segmentation output_shape is required')
        else:
            output_shapes = raw.get('output_shapes')
            if (
                not isinstance(output_shapes, dict)
                or set(output_shapes) != set(output_names)
                or not all(
                    isinstance(shape, list) and shape
                    for shape in output_shapes.values()
                )
            ):
                raise ModelContractError(
                    'panel output_shapes must cover every output name'
                )

        model_file = raw.get('model_file')
        if (
            not isinstance(model_file, str)
            or not model_file
            or Path(model_file).name != model_file
        ):
            raise ModelContractError('model_file must be one filename beside model.json')
        model_sha256 = raw.get('model_sha256')
        if (
            not isinstance(model_sha256, str)
            or len(model_sha256) != 64
            or any(char not in '0123456789abcdef' for char in model_sha256.lower())
        ):
            raise ModelContractError('model_sha256 must be a 64-character hex digest')
        checkpoint_sha256 = raw.get('checkpoint_sha256')
        if (
            not isinstance(checkpoint_sha256, str)
            or len(checkpoint_sha256) != 64
            or any(
                char not in '0123456789abcdef'
                for char in checkpoint_sha256.lower()
            )
        ):
            raise ModelContractError(
                'checkpoint_sha256 must be a 64-character hex digest'
            )
        dataset_version = raw.get('dataset_version')
        dataset_fingerprint = raw.get('dataset_fingerprint')
        git_commit = raw.get('git_commit')
        if not isinstance(dataset_version, str) or not dataset_version:
            raise ModelContractError('dataset_version cannot be empty')
        if (
            not isinstance(dataset_fingerprint, str)
            or len(dataset_fingerprint) != 64
            or any(
                char not in '0123456789abcdef'
                for char in dataset_fingerprint.lower()
            )
        ):
            raise ModelContractError(
                'dataset_fingerprint must be a 64-character hex digest'
            )
        if not isinstance(git_commit, str) or not git_commit:
            raise ModelContractError('git_commit cannot be empty')

        width = _integer(raw, 'input_width')
        height = _integer(raw, 'input_height')
        padding_value = _integer(raw, 'padding_value', minimum=0)
        if padding_value > 255:
            raise ModelContractError('padding_value must be within [0, 255]')
        scale = _number(raw, 'scale')
        if scale <= 0.0:
            raise ModelContractError('scale must be positive')
        mean = _vector(raw, 'mean', 3)
        std = _vector(raw, 'std', 3)
        if any(value <= 0.0 for value in std):
            raise ModelContractError('std entries must be positive')
        threshold = _number(raw, 'threshold')
        if task == 'dirt_segmentation' and not 0.0 < threshold < 1.0:
            raise ModelContractError('segmentation threshold must be within (0, 1)')
        if task == 'panel_detection' and not 0.0 <= threshold <= 1.0:
            raise ModelContractError('detection threshold must be within [0, 1]')
        _validate_task_contract(raw, task)

        manifest = cls(
            path=path,
            raw=raw,
            manifest_version=_integer(raw, 'manifest_version'),
            task=task,
            model_file=model_file,
            model_sha256=model_sha256.lower(),
            onnx_opset=_integer(raw, 'onnx_opset', minimum=11),
            checkpoint_sha256=checkpoint_sha256.lower(),
            input_width=width,
            input_height=height,
            resize=resize,
            padding_value=padding_value,
            color=color,
            dtype=dtype,
            channel_order=channel_order,
            scale=scale,
            mean=mean,
            std=std,
            output_activation=activation,
            output_layout=output_layout,
            output_channel=_integer(raw, 'output_channel', minimum=0),
            threshold=threshold,
            dataset_version=dataset_version,
            dataset_fingerprint=dataset_fingerprint.lower(),
            git_commit=git_commit,
        )
        if verify_model_hash:
            if not manifest.model_path.is_file():
                raise ModelContractError(
                    f'model file declared by manifest is missing: {manifest.model_path}'
                )
            actual = sha256_file(manifest.model_path)
            if actual != manifest.model_sha256:
                raise ModelContractError(
                    f'model SHA-256 mismatch: expected {manifest.model_sha256}, got {actual}'
                )
        return manifest

    def verify_onnx_session(self, session: Any) -> None:
        """Check actual ONNX input/output metadata before accepting results."""
        inputs = session.get_inputs()
        outputs = session.get_outputs()
        try:
            metadata = session.get_modelmeta().custom_metadata_map
        except (AttributeError, TypeError) as exc:
            raise ModelContractError(
                'ONNX model is missing required DA-DAKA custom metadata'
            ) from exc
        expected_metadata = {
            'da_daka.task': self.task,
            'da_daka.output_activation': self.output_activation,
            'da_daka.manifest_version': str(self.manifest_version),
            'da_daka.onnx_opset': str(self.onnx_opset),
        }
        for key, expected_value in expected_metadata.items():
            if metadata.get(key) != expected_value:
                raise ModelContractError(
                    f'ONNX metadata {key}={metadata.get(key)!r} does not match '
                    f'{expected_value!r}'
                )
        if len(inputs) != 1:
            raise ModelContractError('exactly one ONNX input is required')
        if not _shape_matches(inputs[0].shape, self.input_shape):
            raise ModelContractError(
                f'ONNX input shape {inputs[0].shape} does not match {self.input_shape}'
            )
        expected_outputs = self.raw['output_names']
        actual_names = [item.name for item in outputs]
        if actual_names != expected_outputs:
            raise ModelContractError(
                f'ONNX outputs {actual_names} do not match {expected_outputs}'
            )
        if self.task == 'dirt_segmentation':
            if len(outputs) != 1:
                raise ModelContractError('segmentation model needs exactly one output')
            expected_shape = self.raw['output_shape']
            if not _shape_matches(outputs[0].shape, expected_shape):
                raise ModelContractError(
                    f'ONNX output shape {outputs[0].shape} does not match {expected_shape}'
                )
        else:
            expected_shapes = self.raw['output_shapes']
            for output in outputs:
                expected_shape = expected_shapes[output.name]
                if not _shape_matches(output.shape, expected_shape):
                    raise ModelContractError(
                        f'ONNX output {output.name} shape {output.shape} does not '
                        f'match {expected_shape}'
                    )


def _shape_matches(actual: Sequence[Any], expected: Sequence[Any]) -> bool:
    if len(actual) != len(expected):
        return False
    for left, right in zip(actual, expected):
        if isinstance(right, str) or right in {-1, None} or left in {None, 'None'}:
            continue
        if isinstance(left, str):
            continue
        if int(left) != int(right):
            return False
    return True


def _validate_task_contract(raw: Mapping[str, Any], task: str) -> None:
    """Require every task-specific postprocess value to be explicit."""
    if task == 'panel_detection':
        if raw.get('box_coordinates') not in {
            'input_pixels',
            'input_normalized',
        }:
            raise ModelContractError(
                'box_coordinates must be input_pixels or input_normalized'
            )
        _integer(raw, 'panel_label_id', minimum=0)
        _integer(raw, 'maximum_detections')
        nms_threshold = _number(raw, 'nms_iou_threshold')
        if not 0.0 < nms_threshold < 1.0:
            raise ModelContractError('nms_iou_threshold must be within (0, 1)')
        return
    _integer(raw, 'minimum_component_area', minimum=0)
    minimum_ratio = _number(raw, 'minimum_component_area_ratio')
    if not 0.0 <= minimum_ratio < 1.0:
        raise ModelContractError(
            'minimum_component_area_ratio must be within [0, 1)'
        )
    policy = raw.get('target_selection')
    if not isinstance(policy, dict):
        raise ModelContractError('target_selection must be an object')
    weights = tuple(
        _number(policy, name)
        for name in (
            'area_weight',
            'confidence_weight',
            'target_distance_weight',
        )
    )
    if any(value < 0.0 for value in weights) or sum(weights) <= 0.0:
        raise ModelContractError(
            'target_selection weights must be non-negative with a positive sum'
        )
