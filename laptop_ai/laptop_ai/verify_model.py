"""Verify an ONNX bundle contract without running autonomous perception."""

from __future__ import annotations

import argparse
import json

from laptop_ai.model_contract import ModelManifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', required=True)
    parser.add_argument(
        '--task',
        choices=('panel_detection', 'dirt_segmentation'),
        default=None,
    )
    parser.add_argument('--require-deployment-approved', action='store_true')
    parser.add_argument(
        '--allow-test-only',
        action='store_true',
        help='explicit inspection mode; never implies production approval',
    )
    args = parser.parse_args()

    import onnxruntime as ort

    manifest = ModelManifest.load(
        args.manifest,
        expected_task=args.task,
        require_deployment_approved=args.require_deployment_approved,
        allow_test_only=args.allow_test_only,
    )
    if 'CPUExecutionProvider' not in ort.get_available_providers():
        raise RuntimeError('CPUExecutionProvider is required for contract inspection')
    session = ort.InferenceSession(
        str(manifest.model_path),
        providers=['CPUExecutionProvider'],
    )
    manifest.verify_onnx_session(session)
    report = {
        'status': 'compatible',
        'task': manifest.task,
        'architecture_family': manifest.architecture_family,
        'model_sha256': manifest.model_sha256,
        'checkpoint_sha256': manifest.checkpoint_sha256,
        'onnx_opset': manifest.onnx_opset,
        'release_id': manifest.release_id,
        'training_run_id': manifest.training_run_id,
        'export_timestamp': manifest.export_timestamp,
        'test_only': manifest.test_only,
        'deployment_approved': manifest.deployment_approved,
        'safety': manifest.safety,
        'dataset_version': manifest.dataset_version,
        'dataset_fingerprint': manifest.dataset_fingerprint,
        'input_shape': list(manifest.input_shape),
        'input_name': manifest.input_name,
        'output_names': manifest.raw['output_names'],
        'output_activation': manifest.output_activation,
        'threshold': manifest.threshold,
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
