"""Shared, non-fabricating training run metadata helpers."""

from __future__ import annotations

import json
from pathlib import Path
import random
import subprocess

import numpy as np
import yaml


def load_config(path):
    raw = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if not isinstance(raw, dict):
        raise ValueError('training config must be a YAML object')
    return raw


def dataset_manifest(root):
    return json.loads(
        (Path(root) / 'dataset_manifest.json').read_text(encoding='utf-8')
    )


def git_commit():
    try:
        return subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return 'unknown'


def choose_device(requested):
    import torch

    if requested == 'cuda' and not torch.cuda.is_available():
        raise RuntimeError('CUDA training was requested but is unavailable')
    return torch.device(requested)


def seed_training(seed, *, deterministic=True):
    """Seed Python/NumPy/Torch and request deterministic kernels when enabled."""
    import torch

    value = int(seed)
    random.seed(value)
    np.random.seed(value)
    torch.manual_seed(value)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(value)
    if deterministic:
        torch.use_deterministic_algorithms(True)
        if hasattr(torch.backends, 'cudnn'):
            torch.backends.cudnn.benchmark = False
            torch.backends.cudnn.deterministic = True
    return value
