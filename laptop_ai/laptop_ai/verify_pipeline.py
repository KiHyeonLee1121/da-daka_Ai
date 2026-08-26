"""Verify the complete panel+dirt model pair before opening network sockets."""

from __future__ import annotations

import argparse
import json

from laptop_ai.model_contract import (
    ModelManifest,
    verify_pipeline_dataset_identity,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--panel-manifest', required=True)
    parser.add_argument('--dirt-manifest', required=True)
    parser.add_argument('--require-deployment-approved', action='store_true')
    parser.add_argument('--allow-test-only', action='store_true')
    args = parser.parse_args()

    import onnxruntime as ort

    if 'CPUExecutionProvider' not in ort.get_available_providers():
        raise RuntimeError('CPUExecutionProvider is required for contract inspection')
    common = {
        'require_deployment_approved': args.require_deployment_approved,
        'allow_test_only': args.allow_test_only,
    }
    panel = ModelManifest.load(
        args.panel_manifest,
        expected_task='panel_detection',
        **common,
    )
    dirt = ModelManifest.load(
        args.dirt_manifest,
        expected_task='dirt_segmentation',
        **common,
    )
    verify_pipeline_dataset_identity(panel, dirt)
    for manifest in (panel, dirt):
        session = ort.InferenceSession(
            str(manifest.model_path),
            providers=['CPUExecutionProvider'],
        )
        manifest.verify_onnx_session(session)
    print(json.dumps({
        'status': 'compatible-model-pair',
        'release_id': panel.release_id,
        'dataset_version': panel.dataset_version,
        'dataset_fingerprint': panel.dataset_fingerprint,
        'deployment_approved': (
            panel.deployment_approved and dirt.deployment_approved
        ),
        'panel': {
            'architecture_family': panel.architecture_family,
            'training_run_id': panel.training_run_id,
            'model_sha256': panel.model_sha256,
            'onnx_opset': panel.onnx_opset,
        },
        'dirt': {
            'architecture_family': dirt.architecture_family,
            'training_run_id': dirt.training_run_id,
            'model_sha256': dirt.model_sha256,
            'onnx_opset': dirt.onnx_opset,
            'threshold': dirt.threshold,
        },
    }, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
