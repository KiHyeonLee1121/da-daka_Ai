"""Exercise every locked split through both real PyTorch dataset loaders."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from da_daka_training.release import (
    DEFAULT_DATASET_FINGERPRINT,
    DEFAULT_DATASET_VERSION,
    verify_dataset_release,
)
from da_daka_training.torch_data import (
    DirtRoiDataset,
    PanelCocoDataset,
    detection_collate,
)


def loader_smoke_test(
    dataset_root,
    *,
    panel_config,
    dirt_config,
    expected_version=DEFAULT_DATASET_VERSION,
    expected_fingerprint=DEFAULT_DATASET_FINGERPRINT,
):
    import torch

    root = Path(dataset_root).expanduser().resolve()
    release_report = verify_dataset_release(
        root,
        expected_version=expected_version,
        expected_fingerprint=expected_fingerprint,
        mode="full",
    )
    results = {"panel_detection": {}, "dirt_segmentation": {}}
    for split in ("train", "validation", "test"):
        panel = PanelCocoDataset(root, split, panel_config, augment=False)
        panel_batch = next(
            iter(
                torch.utils.data.DataLoader(
                    panel,
                    batch_size=1,
                    shuffle=False,
                    num_workers=0,
                    collate_fn=detection_collate,
                )
            )
        )
        panel_image, target = panel_batch[0][0], panel_batch[1][0]
        if panel_image.ndim != 3 or panel_image.shape[0] != 3:
            raise RuntimeError(
                f"invalid panel tensor shape for {split}: {panel_image.shape}"
            )
        if target["boxes"].ndim != 2 or target["boxes"].shape[1] != 4:
            raise RuntimeError(
                f"invalid panel box shape for {split}: {target['boxes'].shape}"
            )
        results["panel_detection"][split] = {
            "samples": len(panel),
            "first_tensor_shape": list(panel_image.shape),
            "first_box_count": int(target["boxes"].shape[0]),
        }

        dirt = DirtRoiDataset(root, split, dirt_config, augment=False)
        dirt_images, dirt_masks = next(
            iter(
                torch.utils.data.DataLoader(
                    dirt,
                    batch_size=1,
                    shuffle=False,
                    num_workers=0,
                )
            )
        )
        dirt_image, dirt_mask = dirt_images[0], dirt_masks[0]
        if dirt_image.ndim != 3 or dirt_image.shape[0] != 3:
            raise RuntimeError(
                f"invalid dirt tensor shape for {split}: {dirt_image.shape}"
            )
        if dirt_mask.ndim != 2 or dirt_mask.shape != dirt_image.shape[1:]:
            raise RuntimeError(
                f"dirt image/mask tensor mismatch for {split}: "
                f"{dirt_image.shape} vs {dirt_mask.shape}"
            )
        results["dirt_segmentation"][split] = {
            "samples": len(dirt),
            "first_tensor_shape": list(dirt_image.shape),
            "first_mask_shape": list(dirt_mask.shape),
            "first_mask_foreground_pixels": int(dirt_mask.count_nonzero()),
        }
    return {
        "status": "LOADERS_READY",
        "dataset_verification": release_report,
        "loaders": results,
    }


def _config(path):
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"config is not a YAML object: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--panel-config", required=True)
    parser.add_argument("--dirt-config", required=True)
    parser.add_argument("--expected-version", default=DEFAULT_DATASET_VERSION)
    parser.add_argument("--expected-fingerprint", default=DEFAULT_DATASET_FINGERPRINT)
    parser.add_argument("--report")
    args = parser.parse_args()
    report = loader_smoke_test(
        args.dataset_root,
        panel_config=_config(args.panel_config),
        dirt_config=_config(args.dirt_config),
        expected_version=args.expected_version,
        expected_fingerprint=args.expected_fingerprint,
    )
    if args.report:
        output = Path(args.report).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
