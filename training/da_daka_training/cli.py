"""Dataset build command-line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from da_daka_training.dataset_builder import build_master_dataset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config = yaml.safe_load(Path(args.config).read_text(encoding='utf-8'))
    output = build_master_dataset(config)
    print(output)


if __name__ == '__main__':
    main()
