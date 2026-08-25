"""Export trained checkpoints into hashed ONNX model bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from da_daka_training.models import (
    create_dirt_model,
    create_panel_model,
    dirt_binary_logit_wrapper,
    panel_three_output_wrapper,
)
from da_daka_training.train_common import git_commit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--metrics", required=True)
    parser.add_argument("--threshold", required=True, type=float)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    import onnx
    import torch

    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    task = checkpoint.get("task")
    config = dict(checkpoint["config"])
    config["pretrained"] = False
    preprocess = config["preprocess"]
    input_height = int(preprocess["input_height"])
    input_width = int(preprocess["input_width"])
    dummy = torch.zeros((1, 3, input_height, input_width), dtype=torch.float32)
    model_path = output / "model.onnx"
    if task == "dirt_segmentation":
        model = create_dirt_model(config)
        model.load_state_dict(checkpoint["model_state"])
        wrapper = dirt_binary_logit_wrapper(model.eval(), input_height, input_width)
        output_names = ["mask_logits"]
        dynamic_axes = None
    elif task == "panel_detection":
        model = create_panel_model(config)
        model.load_state_dict(checkpoint["model_state"])
        wrapper = panel_three_output_wrapper(model.eval())
        output_names = ["boxes", "scores", "labels"]
        dynamic_axes = {
            "boxes": {0: "detections"},
            "scores": {0: "detections"},
            "labels": {0: "detections"},
        }
    else:
        raise ValueError(f"unsupported checkpoint task: {task!r}")
    onnx_opset = 17
    torch.onnx.export(
        wrapper.eval(),
        dummy,
        model_path,
        input_names=["images"],
        output_names=output_names,
        opset_version=onnx_opset,
        do_constant_folding=True,
        dynamic_axes=dynamic_axes,
        # PyTorch 2.9+ defaults to the torch.export-based exporter, which may
        # silently retain a newer opset when downgrade fails.  The deployed
        # Hailo/ORT contract currently requires an exact, inspectable opset 17.
        dynamo=False,
    )
    exported = onnx.load(str(model_path))
    default_domain_opsets = [
        int(item.version)
        for item in exported.opset_import
        if item.domain in {"", "ai.onnx"}
    ]
    if default_domain_opsets != [onnx_opset]:
        raise RuntimeError(
            f"exported ONNX opset mismatch: expected {onnx_opset}, "
            f"found {default_domain_opsets}"
        )
    onnx.helper.set_model_props(
        exported,
        {
            "da_daka.task": task,
            "da_daka.output_activation": (
                "logits" if task == "dirt_segmentation" else "none"
            ),
            "da_daka.manifest_version": "1",
            "da_daka.onnx_opset": str(onnx_opset),
        },
    )
    onnx.checker.check_model(exported)
    onnx.save(exported, str(model_path))
    model_sha = _sha256(model_path)
    metrics_source = Path(args.metrics).resolve()
    metrics = json.loads(metrics_source.read_text(encoding="utf-8"))
    metrics_bundle = {
        "task": task,
        "selected_threshold": args.threshold,
        "selection_requires_human_safety_review": True,
        "source_report_sha256": _sha256(metrics_source),
        "source_report": metrics,
    }
    (output / "metrics.json").write_text(
        json.dumps(metrics_bundle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "manifest_version": 1,
        "task": task,
        "model_file": "model.onnx",
        "model_sha256": model_sha,
        "onnx_opset": onnx_opset,
        "checkpoint_sha256": _sha256(Path(args.checkpoint).resolve()),
        "input_width": input_width,
        "input_height": input_height,
        "resize": "letterbox",
        "padding_value": int(preprocess.get("padding_value", 114)),
        "color": str(preprocess.get("color", "RGB")).upper(),
        "dtype": "float32",
        "channel_order": "NCHW",
        "scale": float(preprocess.get("scale", 1.0 / 255.0)),
        "mean": [float(value) for value in preprocess.get("mean", [0.0] * 3)],
        "std": [float(value) for value in preprocess.get("std", [1.0] * 3)],
        "output_activation": "logits" if task == "dirt_segmentation" else "none",
        "output_layout": "NCHW",
        "output_channel": 0,
        "output_names": output_names,
        "threshold": float(args.threshold),
        "threshold_report_sha256": _sha256(output / "metrics.json"),
        "dataset_version": checkpoint["dataset_version"],
        "dataset_fingerprint": checkpoint["dataset_fingerprint"],
        "git_commit": git_commit(),
    }
    if task == "dirt_segmentation":
        postprocess = config.get("postprocess", {})
        manifest.update(
            {
                "output_shape": [1, 1, input_height, input_width],
                "minimum_component_area": int(
                    postprocess.get("minimum_component_area", 1)
                ),
                "minimum_component_area_ratio": float(
                    postprocess.get("minimum_component_area_ratio", 0.0)
                ),
                "target_selection": postprocess.get(
                    "target_selection",
                    {
                        "area_weight": 0.45,
                        "confidence_weight": 0.35,
                        "target_distance_weight": 0.20,
                    },
                ),
            }
        )
    else:
        postprocess = config.get("postprocess", {})
        manifest.update(
            {
                "output_shapes": {
                    "boxes": ["detections", 4],
                    "scores": ["detections"],
                    "labels": ["detections"],
                },
                "box_coordinates": "input_pixels",
                "panel_label_id": 1,
                "maximum_detections": int(postprocess.get("maximum_detections", 32)),
                "nms_iou_threshold": float(postprocess.get("nms_iou_threshold", 0.5)),
            }
        )
    (output / "model.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "hailo_deployment.json").write_text(
        json.dumps(
            {
                "status": "NOT_COMPILED_OR_HARDWARE_VALIDATED",
                "target_architecture": "hailo8l",
                "source_model_sha256": model_sha,
                "required_steps": [
                    "install matching Hailo DFC and HailoRT releases",
                    "parse ONNX and confirm supported operators",
                    "optimize with representative IMX708 calibration images",
                    "compile HEF for Hailo-8L",
                    "compare ONNX and HEF accuracy using the same validation set",
                    "measure end-to-end Pi latency before selecting production backend",
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
