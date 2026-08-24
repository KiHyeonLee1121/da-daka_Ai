from types import SimpleNamespace

import pytest

from laptop_ai.production_benchmark import _verify_dataset_identity


def test_production_benchmark_requires_model_dataset_identity():
    manifest = SimpleNamespace(
        dataset_version='dataset-v1',
        dataset_fingerprint='a' * 64,
    )
    _verify_dataset_identity(
        manifest,
        {
            'dataset_version': 'dataset-v1',
            'dataset_fingerprint': 'a' * 64,
        },
    )
    with pytest.raises(ValueError, match='does not match'):
        _verify_dataset_identity(
            manifest,
            {
                'dataset_version': 'dataset-v2',
                'dataset_fingerprint': 'b' * 64,
            },
        )
