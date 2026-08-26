"""End-to-end segmentation benchmark over real validation panel ROIs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import time

import cv2
import yaml

from laptop_ai.segmentation_benchmark import percentile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--dataset-root', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--maximum-samples', type=int, default=0)
    parser.add_argument(
        '--allow-unapproved',
        action='store_true',
        help='measure a trained review-pending bundle without approving it',
    )
    args = parser.parse_args()
    from laptop_ai.onnx_dirt_detector import OnnxDirtSegmenter

    config = yaml.safe_load(Path(args.config).read_text(encoding='utf-8'))
    model = config['dirt_model']
    backend = str(model.get('backend', 'cuda'))
    detector = OnnxDirtSegmenter(
        str(model['manifest']),
        backend=backend,
        performance=config.get('performance'),
        require_deployment_approved=not args.allow_unapproved,
    )
    root = Path(args.dataset_root)
    dataset_manifest = json.loads(
        (root / 'dataset_manifest.json').read_text(encoding='utf-8')
    )
    _verify_dataset_identity(detector.manifest, dataset_manifest)
    samples = [
        json.loads(line) for line in
        (root / 'dirt_segmentation/samples.jsonl').read_text(encoding='utf-8').splitlines()
        if line.strip() and json.loads(line)['split'] == 'validation'
    ]
    if args.maximum_samples > 0:
        samples = samples[:args.maximum_samples]
    if not samples:
        raise ValueError('no validation ROI samples are available')
    timings = []
    dirty_results = 0
    for sample in samples:
        image = cv2.imread(
            str(root / 'dirt_segmentation' / sample['image']),
            cv2.IMREAD_COLOR,
        )
        if image is None:
            raise ValueError(f'cannot read ROI {sample["image"]}')
        started = time.perf_counter()
        result = detector.detect(image)
        timings.append((time.perf_counter() - started) * 1000.0)
        dirty_results += int(result is not None)
    mean_ms = statistics.fmean(timings)
    gpu_memory_mb = _nvidia_process_memory_mb() if backend == 'cuda' else None
    report = {
        'benchmark_type': 'real_validation_roi_end_to_end',
        'sample_count': len(samples),
        'model': detector.model_name,
        'model_sha256': detector.model_sha256,
        'dataset_version': detector.dataset_version,
        'input_width': detector.manifest.input_width,
        'input_height': detector.manifest.input_height,
        'mean_ms': mean_ms,
        'p50_ms': percentile(timings, 0.50),
        'p95_ms': percentile(timings, 0.95),
        'p99_ms': percentile(timings, 0.99),
        'effective_fps': 1000.0 / mean_ms,
        'dirty_result_count': dirty_results,
        'backend': backend,
        'gpu_memory_mb': gpu_memory_mb,
        'gpu_memory_note': (
            'current-process nvidia-smi allocation when available; use the '
            'target vendor profiler for peak memory and HailoRT deployments'
            if gpu_memory_mb is not None else
            'nvidia-smi process memory was unavailable; no value was fabricated'
        ),
    }
    Path(args.output).write_text(
        json.dumps(report, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )
    print(json.dumps(report, indent=2, sort_keys=True))


def _nvidia_process_memory_mb() -> float | None:
    try:
        output = subprocess.run(
            [
                'nvidia-smi',
                '--query-compute-apps=pid,used_memory',
                '--format=csv,noheader,nounits',
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    current_pid = os.getpid()
    values = []
    for line in output.splitlines():
        fields = [value.strip() for value in line.split(',')]
        if len(fields) != 2:
            continue
        try:
            pid = int(fields[0])
            memory = float(fields[1])
        except ValueError:
            continue
        if pid == current_pid:
            values.append(memory)
    return float(sum(values)) if values else None


def _verify_dataset_identity(model_manifest, dataset_manifest: dict) -> None:
    """Reject benchmarks against data other than the model's declared dataset."""
    expected = (
        model_manifest.dataset_version,
        model_manifest.dataset_fingerprint,
    )
    actual = (
        dataset_manifest.get('dataset_version'),
        dataset_manifest.get('dataset_fingerprint'),
    )
    if actual != expected:
        raise ValueError(
            'benchmark dataset identity does not match model manifest: '
            f'expected version/fingerprint={expected}, got {actual}'
        )


if __name__ == '__main__':
    main()
