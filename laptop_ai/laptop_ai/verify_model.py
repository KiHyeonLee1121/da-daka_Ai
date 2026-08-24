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
    args = parser.parse_args()

    import onnxruntime as ort

    manifest = ModelManifest.load(args.manifest, expected_task=args.task)
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
        'model_sha256': manifest.model_sha256,
        'checkpoint_sha256': manifest.checkpoint_sha256,
        'dataset_version': manifest.dataset_version,
        'dataset_fingerprint': manifest.dataset_fingerprint,
        'input_shape': list(manifest.input_shape),
        'output_names': manifest.raw['output_names'],
        'output_activation': manifest.output_activation,
        'threshold': manifest.threshold,
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
