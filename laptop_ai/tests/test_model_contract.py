import hashlib
import json

import pytest

from laptop_ai.model_contract import (
    ModelContractError,
    ModelManifest,
    verify_pipeline_dataset_identity,
)


class Io:
    def __init__(self, name, shape):
        self.name = name
        self.shape = shape


class Session:
    def __init__(self, input_shape, output_shape, activation='logits'):
        self._inputs = [Io('images', input_shape)]
        self._outputs = [Io('mask_logits', output_shape)]
        self._metadata = type('Meta', (), {'custom_metadata_map': {
            'da_daka.task': 'dirt_segmentation',
            'da_daka.architecture_family': 'torchvision.lraspp_mobilenet_v3_large',
            'da_daka.output_activation': activation,
            'da_daka.manifest_version': '1',
            'da_daka.onnx_opset': '17',
            'da_daka.release_id': 'release-v1',
            'da_daka.training_run_id': 'dirt-run-v1',
        }})()

    def get_inputs(self):
        return self._inputs

    def get_outputs(self):
        return self._outputs

    def get_modelmeta(self):
        return self._metadata


class PanelSession:
    def __init__(self, score_shape):
        self._inputs = [Io('images', [1, 3, 384, 640])]
        self._outputs = [
            Io('boxes', ['detections', 4]),
            Io('scores', score_shape),
            Io('labels', ['detections']),
        ]
        self._metadata = type('Meta', (), {'custom_metadata_map': {
            'da_daka.task': 'panel_detection',
            'da_daka.architecture_family': 'torchvision.fasterrcnn_mobilenet_v3_large_fpn',
            'da_daka.output_activation': 'none',
            'da_daka.manifest_version': '1',
            'da_daka.onnx_opset': '17',
            'da_daka.release_id': 'release-v1',
            'da_daka.training_run_id': 'dirt-run-v1',
        }})()

    def get_inputs(self):
        return self._inputs

    def get_outputs(self):
        return self._outputs

    def get_modelmeta(self):
        return self._metadata


def manifest(tmp_path, **updates):
    model = tmp_path / 'model.onnx'
    model.write_bytes(b'not-a-real-model-but-hashable')
    threshold_report = tmp_path / 'metrics.json'
    threshold_report.write_text(
        json.dumps({'selection_split': 'validation', 'selected_threshold': 0.4})
    )
    raw = {
        'manifest_version': 1,
        'task': 'dirt_segmentation',
        'architecture_family': 'torchvision.lraspp_mobilenet_v3_large',
        'model_file': 'model.onnx',
        'model_sha256': hashlib.sha256(model.read_bytes()).hexdigest(),
        'onnx_opset': 17,
        'checkpoint_sha256': 'e' * 64,
        'release_id': 'release-v1',
        'training_run_id': 'dirt-run-v1',
        'export_timestamp': '2026-08-26T06:00:00+00:00',
        'export_tool_versions': {'python': '3.12.3', 'onnx': '1.22.0'},
        'class_mapping': {'clean': 0, 'dirt': 1},
        'test_only': False,
        'deployment_approved': False,
        'safety': 'REQUIRES_HUMAN_REVIEW',
        'input_name': 'images',
        'input_shape': [1, 3, 384, 640],
        'input_width': 640,
        'input_height': 384,
        'resize': 'letterbox',
        'padding_value': 114,
        'color': 'RGB',
        'dtype': 'float32',
        'channel_order': 'NCHW',
        'scale': 1.0 / 255.0,
        'mean': [0.0, 0.0, 0.0],
        'std': [1.0, 1.0, 1.0],
        'output_activation': 'logits',
        'output_layout': 'NCHW',
        'output_channel': 0,
        'output_names': ['mask_logits'],
        'output_shape': [1, 1, 384, 640],
        'threshold': 0.4,
        'threshold_report_sha256': hashlib.sha256(
            threshold_report.read_bytes()
        ).hexdigest(),
        'minimum_component_area': 8,
        'minimum_component_area_ratio': 0.0001,
        'target_selection': {
            'area_weight': 0.45,
            'confidence_weight': 0.35,
            'target_distance_weight': 0.20,
        },
        'dataset_version': 'dataset-v1',
        'dataset_fingerprint': 'f' * 64,
        'git_commit': 'abc123',
    }
    raw.update(updates)
    path = tmp_path / 'model.json'
    path.write_text(json.dumps(raw))
    return path


def test_input_shape_mismatch_fails_closed(tmp_path):
    loaded = ModelManifest.load(manifest(tmp_path))
    with pytest.raises(ModelContractError, match='input shape'):
        loaded.verify_onnx_session(Session([1, 3, 512, 512], [1, 1, 384, 640]))


def test_output_shape_mismatch_fails_closed(tmp_path):
    loaded = ModelManifest.load(manifest(tmp_path))
    with pytest.raises(ModelContractError, match='output shape'):
        loaded.verify_onnx_session(Session([1, 3, 384, 640], [1, 1, 192, 320]))


def test_activation_must_not_be_auto_guessed(tmp_path):
    with pytest.raises(ModelContractError, match='output_activation'):
        ModelManifest.load(manifest(tmp_path, output_activation='auto'))


def test_activation_metadata_mismatch_fails_closed(tmp_path):
    loaded = ModelManifest.load(manifest(tmp_path))
    with pytest.raises(ModelContractError, match='output_activation'):
        loaded.verify_onnx_session(
            Session([1, 3, 384, 640], [1, 1, 384, 640], 'probability')
        )


def test_onnx_opset_metadata_mismatch_fails_closed(tmp_path):
    loaded = ModelManifest.load(manifest(tmp_path, onnx_opset=18))
    with pytest.raises(ModelContractError, match='onnx_opset'):
        loaded.verify_onnx_session(
            Session([1, 3, 384, 640], [1, 1, 384, 640])
        )


def test_model_sha_mismatch_fails_closed(tmp_path):
    with pytest.raises(ModelContractError, match='SHA-256 mismatch'):
        ModelManifest.load(manifest(tmp_path, model_sha256='0' * 64))


def test_threshold_report_sha_mismatch_fails_closed(tmp_path):
    with pytest.raises(ModelContractError, match='threshold report SHA-256 mismatch'):
        ModelManifest.load(manifest(tmp_path, threshold_report_sha256='0' * 64))


def test_unknown_manifest_version_fails_closed(tmp_path):
    with pytest.raises(ModelContractError, match='manifest_version'):
        ModelManifest.load(manifest(tmp_path, manifest_version=2))


def test_input_name_and_declared_shape_are_exact(tmp_path):
    loaded = ModelManifest.load(manifest(tmp_path, input_name='input'))
    with pytest.raises(ModelContractError, match='input name'):
        loaded.verify_onnx_session(
            Session([1, 3, 384, 640], [1, 1, 384, 640])
        )
    with pytest.raises(ModelContractError, match='input_shape'):
        ModelManifest.load(manifest(tmp_path, input_shape=[1, 3, 512, 512]))


def test_panel_output_shape_mismatch_fails_closed(tmp_path):
    loaded = ModelManifest.load(
        manifest(
            tmp_path,
            task='panel_detection',
            architecture_family='torchvision.fasterrcnn_mobilenet_v3_large_fpn',
            output_activation='none',
            output_names=['boxes', 'scores', 'labels'],
            output_shapes={
                'boxes': ['detections', 4],
                'scores': ['detections'],
                'labels': ['detections'],
            },
            box_coordinates='input_pixels',
            class_mapping={'background': 0, 'solar_panel': 1},
            panel_label_id=1,
            maximum_detections=32,
            nms_iou_threshold=0.5,
        )
    )
    with pytest.raises(ModelContractError, match='scores.*shape'):
        loaded.verify_onnx_session(PanelSession(['detections', 1]))


def test_pipeline_models_must_use_the_same_dataset_identity():
    left = type('Manifest', (), {
        'dataset_version': 'dataset-v1',
        'dataset_fingerprint': 'a' * 64,
        'release_id': 'release-v1',
    })()
    right = type('Manifest', (), {
        'dataset_version': 'dataset-v2',
        'dataset_fingerprint': 'b' * 64,
        'release_id': 'release-v2',
    })()
    with pytest.raises(ModelContractError, match='dataset.*mismatch'):
        verify_pipeline_dataset_identity(left, right)


def test_test_only_bundle_requires_explicit_mode(tmp_path):
    path = manifest(
        tmp_path,
        test_only=True,
        deployment_approved=False,
        safety='TEST_ONLY',
    )
    with pytest.raises(ModelContractError, match='test-only model rejected'):
        ModelManifest.load(path)
    loaded = ModelManifest.load(path, allow_test_only=True)
    assert loaded.test_only is True


def test_production_requires_human_approval(tmp_path):
    path = manifest(tmp_path)
    with pytest.raises(ModelContractError, match='not deployment-approved'):
        ModelManifest.load(path, require_deployment_approved=True)
    loaded = ModelManifest.load(
        manifest(
            tmp_path,
            deployment_approved=True,
            safety='PRODUCTION_APPROVED',
        ),
        require_deployment_approved=True,
    )
    assert loaded.deployment_approved is True


def test_release_mismatch_rejects_model_pair():
    left = type('Manifest', (), {
        'dataset_version': 'dataset-v1',
        'dataset_fingerprint': 'a' * 64,
        'release_id': 'release-one',
    })()
    right = type('Manifest', (), {
        'dataset_version': 'dataset-v1',
        'dataset_fingerprint': 'a' * 64,
        'release_id': 'release-two',
    })()
    with pytest.raises(ModelContractError, match='release mismatch'):
        verify_pipeline_dataset_identity(left, right)
