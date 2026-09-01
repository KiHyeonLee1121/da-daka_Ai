"""Fail-closed verification and local staging for a built dataset release.

This module never rebuilds or repairs a dataset.  It verifies the immutable
release contract produced by :mod:`dataset_builder`, then optionally copies a
verified Drive release to a local training filesystem.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

DEFAULT_DATASET_VERSION = "da-daka-0fe4fc5f136e2a79"
DEFAULT_DATASET_FINGERPRINT = (
    "0fe4fc5f136e2a79240c3ddf7ba731d45a187b044c9a7a9fdf5bff956145a9fe"
)
FAILURE_BANNER = "DATASET INCOMPLETE OR WRONG RELEASE"
SPLITS = ("train", "validation", "test")


class DatasetReleaseError(RuntimeError):
    """The supplied path is incomplete or is not the expected release."""


def verify_dataset_release(
    dataset_root: str | Path,
    *,
    expected_version: str = DEFAULT_DATASET_VERSION,
    expected_fingerprint: str = DEFAULT_DATASET_FINGERPRINT,
    mode: str = "full",
) -> dict[str, Any]:
    """Verify identity, completeness and (in full mode) file contents.

    ``metadata`` mode is intended for a mounted Drive preflight: it validates
    every reference and count and recomputes the canonical dataset fingerprint
    without decoding all media.  ``full`` mode additionally hashes all master
    and detector images and decodes every ROI/mask; use it after local staging.
    """
    if mode not in {"metadata", "full"}:
        _fail(f"unsupported verification mode: {mode!r}")
    root = Path(dataset_root).expanduser().resolve()
    if not root.is_dir():
        _fail(f"dataset root is not a directory: {root}")

    required = (
        "dataset_summary.json",
        "dataset_manifest.json",
        "provenance.json",
        "annotations/master.json",
        "annotations/train.json",
        "annotations/validation.json",
        "annotations/test.json",
        "panel_detection/annotations/train.json",
        "panel_detection/annotations/validation.json",
        "panel_detection/annotations/test.json",
        "dirt_segmentation/samples.jsonl",
        "dirt_segmentation/dataset.json",
    )
    for relative in required:
        _require_file(root, relative)

    summary = _read_json(root / "dataset_summary.json")
    manifest = _read_json(root / "dataset_manifest.json")
    provenance = _read_json(root / "provenance.json")
    master = _read_json(root / "annotations/master.json")
    dirt_dataset = _read_json(root / "dirt_segmentation/dataset.json")
    if not isinstance(provenance, list):
        _fail("provenance.json must be a JSON array")

    version_values = {
        "expected": expected_version,
        "manifest": manifest.get("dataset_version"),
        "summary": summary.get("dataset_version"),
        "master": master.get("info", {}).get("version"),
        "dirt_dataset": dirt_dataset.get("source_dataset_version"),
    }
    fingerprint_values = {
        "expected": expected_fingerprint,
        "manifest": manifest.get("dataset_fingerprint"),
        "summary": summary.get("dataset_fingerprint"),
        "master": master.get("info", {}).get("dataset_fingerprint"),
        "dirt_dataset": dirt_dataset.get("source_dataset_fingerprint"),
    }
    _require_identical("dataset_version", version_values)
    _require_identical("dataset_fingerprint", fingerprint_values)
    if not isinstance(expected_fingerprint, str) or len(expected_fingerprint) != 64:
        _fail(
            "expected dataset fingerprint must be 64 lowercase hexadecimal characters"
        )
    try:
        int(expected_fingerprint, 16)
    except ValueError:
        _fail("expected dataset fingerprint must be lowercase hexadecimal")
    if expected_fingerprint.lower() != expected_fingerprint:
        _fail("expected dataset fingerprint must be lowercase hexadecimal")

    category_contract = manifest.get("category_contract")
    if category_contract != {"solar_panel": 1, "dirt": 2}:
        _fail(f"unexpected category contract: {category_contract!r}")
    categories = {
        str(item.get("name")): int(item.get("id"))
        for item in master.get("categories", [])
    }
    if categories != category_contract:
        _fail(f"master category contract mismatch: {categories!r}")

    images = master.get("images")
    annotations = master.get("annotations")
    if not isinstance(images, list) or not isinstance(annotations, list):
        _fail("master COCO must contain image and annotation arrays")
    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        _fail("dataset manifest counts must be an object")
    if summary.get("counts") != counts:
        _fail("dataset summary and manifest counts differ")
    _expect_count("master images", counts.get("images"), len(images))
    _expect_count("master annotations", counts.get("annotations"), len(annotations))
    _expect_count("provenance rows", len(images), len(provenance))

    image_ids = [int(item["id"]) for item in images]
    if len(set(image_ids)) != len(image_ids):
        _fail("master COCO contains duplicate image ids")
    image_by_id = {int(item["id"]): item for item in images}
    provenance_by_id = _unique_by_integer_key(provenance, "image_id", "provenance")
    if set(provenance_by_id) != set(image_by_id):
        _fail("provenance image ids do not match master COCO image ids")
    annotation_ids = [int(item["id"]) for item in annotations]
    if len(set(annotation_ids)) != len(annotation_ids):
        _fail("master COCO contains duplicate annotation ids")
    orphan_ids = sorted(
        {int(item["image_id"]) for item in annotations} - set(image_by_id)
    )
    if orphan_ids:
        _fail(
            f"master COCO contains orphan annotations for image ids {orphan_ids[:10]}"
        )

    recomputed_fingerprint = _canonical_fingerprint(
        manifest=manifest,
        master=master,
        provenance=provenance,
    )
    if recomputed_fingerprint != expected_fingerprint:
        _fail(
            "canonical fingerprint mismatch: "
            f"expected {expected_fingerprint}, recomputed {recomputed_fingerprint}"
        )

    master_references = set()
    for image_id, image in image_by_id.items():
        path = _referenced_file(root, str(image.get("file_name", "")))
        master_references.add(path.relative_to(root).as_posix())
        if mode == "full":
            recorded_sha = str(provenance_by_id[image_id].get("sha256", ""))
            actual_sha = _sha256(path)
            if actual_sha != recorded_sha:
                _fail(
                    f"master image SHA-256 mismatch for {path}: "
                    f"manifest {recorded_sha}, actual {actual_sha}"
                )
    actual_master_files = _relative_files(root, root / "images")
    if actual_master_files != master_references:
        _fail(
            _set_mismatch(
                "master image inventory", master_references, actual_master_files
            )
        )

    split_counts = Counter(str(item.get("split")) for item in provenance)
    if dict(counts.get("by_split", {})) != dict(split_counts):
        _fail(
            "manifest split counts do not match provenance: "
            f"manifest={counts.get('by_split')!r}, actual={dict(split_counts)!r}"
        )
    for split in SPLITS:
        if split_counts[split] <= 0:
            _fail(f"required split is empty: {split}")

    panel_reference_paths: set[str] = set()
    panel_image_ids: set[int] = set()
    panel_annotations_total = 0
    for split in SPLITS:
        split_master = _read_json(root / f"annotations/{split}.json")
        panel_coco = _read_json(root / f"panel_detection/annotations/{split}.json")
        expected_ids = {
            image_id
            for image_id, item in provenance_by_id.items()
            if str(item.get("split")) == split
        }
        _expect_id_set(
            f"master {split} images", split_master.get("images"), expected_ids
        )
        _expect_id_set(f"panel {split} images", panel_coco.get("images"), expected_ids)
        expected_split_images = [
            item for item in images if int(item["id"]) in expected_ids
        ]
        expected_split_annotations = [
            item for item in annotations if int(item["image_id"]) in expected_ids
        ]
        if split_master.get("images") != expected_split_images:
            _fail(f"master {split} image metadata differs from master.json")
        if split_master.get("annotations") != expected_split_annotations:
            _fail(f"master {split} annotations differ from master.json")
        expected_panel_images = [
            {
                **item,
                "file_name": f"images/{Path(item['file_name']).name}",
            }
            for item in expected_split_images
        ]
        expected_panel_source_annotations = [
            item for item in expected_split_annotations if int(item["category_id"]) == 1
        ]
        expected_panel_annotations = [
            {**item, "id": index}
            for index, item in enumerate(expected_panel_source_annotations, 1)
        ]
        if panel_coco.get("images") != expected_panel_images:
            _fail(f"panel {split} image metadata differs from master.json")
        if panel_coco.get("annotations") != expected_panel_annotations:
            _fail(f"panel {split} annotations differ from master panel annotations")
        panel_image_ids.update(expected_ids)
        panel_annotations_total += len(panel_coco.get("annotations", []))
        if not panel_coco.get("annotations"):
            _fail(f"panel detection annotations are empty for split: {split}")
        for image in panel_coco.get("images", []):
            path = _referenced_file(
                root / "panel_detection",
                str(image.get("file_name", "")),
            )
            relative = path.relative_to(root).as_posix()
            panel_reference_paths.add(relative)
            if mode == "full":
                source_sha = str(provenance_by_id[int(image["id"])].get("sha256", ""))
                if _sha256(path) != source_sha:
                    _fail(f"panel detector image SHA-256 mismatch: {path}")
    if panel_image_ids != set(image_by_id):
        _fail("panel detection split image ids do not cover the master dataset")
    actual_panel_files = _relative_files(root, root / "panel_detection/images")
    if actual_panel_files != panel_reference_paths:
        _fail(
            _set_mismatch(
                "panel image inventory", panel_reference_paths, actual_panel_files
            )
        )

    samples = _read_jsonl(root / "dirt_segmentation/samples.jsonl")
    dataset_samples = dirt_dataset.get("samples")
    if samples != dataset_samples:
        _fail("dirt samples.jsonl and dataset.json sample inventories differ")
    if not samples:
        _fail("dirt segmentation sample inventory is empty")
    sample_ids = [str(item.get("sample_id", "")) for item in samples]
    if not all(sample_ids) or len(set(sample_ids)) != len(sample_ids):
        _fail("dirt segmentation sample ids are empty or duplicated")
    sample_split_counts = Counter(str(item.get("split")) for item in samples)
    for split in SPLITS:
        if sample_split_counts[split] <= 0:
            _fail(f"dirt segmentation split is empty: {split}")

    dirt_references: set[str] = set()
    clean_samples = dirty_samples = 0
    annotation_by_id = {int(item["id"]): item for item in annotations}
    annotations_by_image: dict[int, list[dict[str, Any]]] = {
        image_id: [] for image_id in image_by_id
    }
    for annotation in annotations:
        annotations_by_image[int(annotation["image_id"])].append(annotation)
    cached_source_id = None
    cached_source_image = None
    cached_source_mask = None
    for sample in samples:
        image_path = _referenced_file(
            root / "dirt_segmentation", str(sample.get("image", ""))
        )
        mask_path = _referenced_file(
            root / "dirt_segmentation", str(sample.get("mask", ""))
        )
        dirt_references.update(
            {
                image_path.relative_to(root).as_posix(),
                mask_path.relative_to(root).as_posix(),
            }
        )
        clean_dirty = str(sample.get("clean_dirty"))
        clean_samples += int(clean_dirty == "clean")
        dirty_samples += int(clean_dirty == "dirty")
        if clean_dirty not in {"clean", "dirty"}:
            _fail(f"invalid clean_dirty value for sample {sample.get('sample_id')!r}")
        if mode == "full":
            source_image_id = int(sample.get("source_image_id", -1))
            if source_image_id not in image_by_id:
                _fail(
                    f"dirt sample references unknown source image: "
                    f"{sample.get('sample_id')!r}"
                )
            if sample.get("split") != provenance_by_id[source_image_id].get("split"):
                _fail(f"dirt sample split mismatch: {sample.get('sample_id')!r}")
            panel_annotation_id = int(sample.get("source_panel_annotation_id", -1))
            panel_annotation = annotation_by_id.get(panel_annotation_id)
            if (
                panel_annotation is None
                or int(panel_annotation["image_id"]) != source_image_id
                or int(panel_annotation["category_id"]) != 1
            ):
                _fail(
                    f"dirt sample panel provenance mismatch: "
                    f"{sample.get('sample_id')!r}"
                )
            if cached_source_id != source_image_id:
                cached_source_id = source_image_id
                cached_source_image, cached_source_mask = _master_image_and_dirt_mask(
                    root,
                    image_by_id[source_image_id],
                    annotations_by_image[source_image_id],
                )
            crop = sample.get("crop_xywh")
            if not isinstance(crop, list) or len(crop) != 4:
                _fail(f"invalid crop_xywh for sample {sample.get('sample_id')!r}")
            left, top, width, height = (int(value) for value in crop)
            source_height, source_width = cached_source_image.shape[:2]
            if (
                left < 0
                or top < 0
                or width <= 0
                or height <= 0
                or left + width > source_width
                or top + height > source_height
            ):
                _fail(
                    f"crop_xywh exceeds source image for sample "
                    f"{sample.get('sample_id')!r}"
                )
            expected_image = cached_source_image[
                top : top + height, left : left + width
            ]
            expected_mask = cached_source_mask[top : top + height, left : left + width]
            _verify_roi_pair(
                image_path,
                mask_path,
                sample,
                expected_image=expected_image,
                expected_mask=expected_mask,
            )
    actual_dirt_files = set()
    for split in SPLITS:
        actual_dirt_files.update(
            _relative_files(root, root / f"dirt_segmentation/{split}/images")
        )
        actual_dirt_files.update(
            _relative_files(root, root / f"dirt_segmentation/{split}/masks")
        )
    if actual_dirt_files != dirt_references:
        _fail(
            _set_mismatch("dirt ROI/mask inventory", dirt_references, actual_dirt_files)
        )

    derived_counts = manifest.get("derived_counts")
    summary_derived = summary.get("derived_counts")
    if derived_counts != summary_derived or not isinstance(derived_counts, dict):
        _fail("manifest and summary derived_counts differ")
    expected_derived = {
        "panel_detection_images": len(images),
        "dirt_segmentation_samples": len(samples),
        "clean_roi_samples": clean_samples,
        "dirty_roi_samples": dirty_samples,
    }
    for name, actual in expected_derived.items():
        _expect_count(name, derived_counts.get(name), actual)

    report = {
        "status": "VERIFIED",
        "verification_mode": mode,
        "dataset_root": str(root),
        "dataset_version": expected_version,
        "dataset_fingerprint": expected_fingerprint,
        "recomputed_fingerprint": recomputed_fingerprint,
        "counts": {
            "master_images": len(images),
            "master_annotations": len(annotations),
            "panel_annotations": panel_annotations_total,
            "dirt_samples": len(samples),
            "clean_dirt_samples": clean_samples,
            "dirty_dirt_samples": dirty_samples,
            "by_master_split": dict(split_counts),
            "by_dirt_split": dict(sample_split_counts),
            "referenced_files": (
                len(master_references)
                + len(panel_reference_paths)
                + len(dirt_references)
                + len(required)
            ),
            "actual_release_files": len(_relative_files(root, root)),
        },
    }
    return report


def stage_dataset_release(
    source_root: str | Path,
    destination_root: str | Path,
    *,
    expected_version: str = DEFAULT_DATASET_VERSION,
    expected_fingerprint: str = DEFAULT_DATASET_FINGERPRINT,
    reuse_verified: bool = False,
) -> dict[str, Any]:
    """Preflight a Drive release, copy atomically, then perform full verification."""
    source = Path(source_root).expanduser().resolve()
    destination = _validate_staging_destination(destination_root, source)
    source_report = verify_dataset_release(
        source,
        expected_version=expected_version,
        expected_fingerprint=expected_fingerprint,
        mode="metadata",
    )
    if destination.exists():
        if not reuse_verified:
            _fail(
                f"staging destination already exists: {destination}; "
                "use --reuse-verified only to reuse an already verified local copy"
            )
        destination_report = verify_dataset_release(
            destination,
            expected_version=expected_version,
            expected_fingerprint=expected_fingerprint,
            mode="full",
        )
        return {
            "status": "REUSED_VERIFIED_LOCAL_DATASET",
            "source_preflight": source_report,
            "destination_verification": destination_report,
        }

    destination.parent.mkdir(parents=True, exist_ok=True)
    source_bytes = sum(
        path.stat().st_size for path in source.rglob("*") if path.is_file()
    )
    free_bytes = shutil.disk_usage(destination.parent).free
    required_bytes = int(source_bytes * 1.05) + 256 * 1024 * 1024
    if free_bytes < required_bytes:
        _fail(
            f"insufficient staging space: need at least {required_bytes} bytes, "
            f"have {free_bytes} bytes"
        )
    staging = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent)
    )
    try:
        shutil.copytree(source, staging, dirs_exist_ok=True, copy_function=shutil.copy2)
        staged_report = verify_dataset_release(
            staging,
            expected_version=expected_version,
            expected_fingerprint=expected_fingerprint,
            mode="full",
        )
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    staged_report["dataset_root"] = str(destination)
    return {
        "status": "STAGED_AND_VERIFIED",
        "source_bytes": source_bytes,
        "source_preflight": source_report,
        "destination_verification": staged_report,
    }


def _canonical_fingerprint(*, manifest, master, provenance) -> str:
    sources = manifest.get("sources")
    split_policy = manifest.get("split_policy")
    if not isinstance(sources, list) or not sources:
        _fail("dataset manifest sources must be a non-empty array")
    if not isinstance(split_policy, dict):
        _fail("dataset manifest split_policy must be an object")
    canonical = {
        "categories": manifest.get("category_contract"),
        "sources": [
            {key: value for key, value in record.items() if key != "source_path"}
            for record in sources
        ],
        "images": master.get("images"),
        "annotations": master.get("annotations"),
        "provenance": [
            {key: value for key, value in item.items() if key != "source_path"}
            for item in provenance
        ],
        "split_policy": split_policy,
    }
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _master_image_and_dirt_mask(root, image_info, annotations):
    import cv2
    import numpy as np

    image_path = _referenced_file(root, str(image_info.get("file_name", "")))
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        _fail(f"cannot decode master image for ROI verification: {image_path}")
    mask = np.zeros(image.shape[:2], dtype=np.uint8)
    for annotation in annotations:
        if int(annotation["category_id"]) != 2:
            continue
        for polygon in annotation.get("segmentation", []):
            points = np.rint(
                np.asarray(polygon, dtype=np.float32).reshape(-1, 2)
            ).astype(np.int32)
            cv2.fillPoly(mask, [points], 255)
    return image, mask


def _verify_roi_pair(
    image_path: Path,
    mask_path: Path,
    sample: dict[str, Any],
    *,
    expected_image,
    expected_mask,
) -> None:
    import cv2
    import numpy as np

    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    if image is None or mask is None:
        _fail(f"cannot decode ROI or mask for sample {sample.get('sample_id')!r}")
    expected_shape = (int(sample.get("height", -1)), int(sample.get("width", -1)))
    if image.shape[:2] != expected_shape or mask.shape != expected_shape:
        _fail(
            f"ROI/mask dimension mismatch for {sample.get('sample_id')!r}: "
            f"expected {expected_shape}, image={image.shape[:2]}, mask={mask.shape}"
        )
    if not np.array_equal(image, expected_image):
        _fail(f"ROI image content mismatch for sample {sample.get('sample_id')!r}")
    if not np.array_equal(mask, expected_mask):
        _fail(f"ROI mask content mismatch for sample {sample.get('sample_id')!r}")
    values = set(int(value) for value in np.unique(mask))
    if not values.issubset({0, 255}):
        _fail(f"mask is not binary for sample {sample.get('sample_id')!r}: {values}")
    nonzero = int(np.count_nonzero(mask))
    if nonzero != int(sample.get("dirt_pixel_count", -1)):
        _fail(f"mask pixel count mismatch for sample {sample.get('sample_id')!r}")
    if str(sample.get("clean_dirty")) == "clean" and nonzero:
        _fail(f"clean sample has a non-zero mask: {sample.get('sample_id')!r}")
    if str(sample.get("clean_dirty")) == "dirty" and not nonzero:
        _fail(f"dirty sample has an all-zero mask: {sample.get('sample_id')!r}")


def _validate_staging_destination(value: str | Path, source: Path) -> Path:
    destination = Path(value).expanduser().resolve()
    if destination == source:
        _fail("staging source and destination must differ")
    if destination == Path(destination.anchor) or destination == Path.home().resolve():
        _fail(f"unsafe staging destination: {destination}")
    try:
        source.relative_to(destination)
    except ValueError:
        pass
    else:
        _fail("staging destination cannot contain the source dataset")
    try:
        destination.relative_to(source)
    except ValueError:
        pass
    else:
        _fail("staging destination cannot be inside the source dataset")
    return destination


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _fail(f"cannot read valid JSON from {path}: {exc}")


def _read_jsonl(path: Path) -> list[Any]:
    values = []
    try:
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if line.strip():
                try:
                    values.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    _fail(f"invalid JSONL at {path}:{line_number}: {exc}")
    except (OSError, UnicodeError) as exc:
        _fail(f"cannot read {path}: {exc}")
    return values


def _require_file(root: Path, relative: str) -> Path:
    path = root / relative
    if not path.is_file():
        _fail(f"required release file is missing: {relative}")
    return path


def _referenced_file(root: Path, relative: str) -> Path:
    if not relative.strip():
        _fail("dataset contains an empty file reference")
    path = (root / Path(relative)).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        _fail(f"dataset file reference escapes its root: {relative!r}")
    if not path.is_file():
        _fail(f"referenced dataset file is missing: {path}")
    return path


def _relative_files(release_root: Path, directory: Path) -> set[str]:
    if not directory.is_dir():
        _fail(f"required dataset directory is missing: {directory}")
    return {
        path.relative_to(release_root).as_posix()
        for path in directory.rglob("*")
        if path.is_file()
    }


def _unique_by_integer_key(
    values: Iterable[dict], key: str, label: str
) -> dict[int, dict]:
    result = {}
    for value in values:
        try:
            item_key = int(value[key])
        except (KeyError, TypeError, ValueError):
            _fail(f"{label} row has invalid {key}: {value!r}")
        if item_key in result:
            _fail(f"{label} contains duplicate {key}: {item_key}")
        result[item_key] = value
    return result


def _expect_id_set(label: str, images: Any, expected: set[int]) -> None:
    if not isinstance(images, list):
        _fail(f"{label} must be an image array")
    actual = {int(item["id"]) for item in images}
    if len(actual) != len(images) or actual != expected:
        _fail(
            f"{label} ids differ from provenance: expected={expected}, actual={actual}"
        )


def _expect_count(label: str, expected: Any, actual: int) -> None:
    try:
        expected_value = int(expected)
    except (TypeError, ValueError):
        _fail(f"{label} expected count is invalid: {expected!r}")
    if expected_value != actual:
        _fail(f"{label} count mismatch: expected {expected_value}, actual {actual}")


def _require_identical(label: str, values: dict[str, Any]) -> None:
    if any(value is None or value == "" for value in values.values()):
        _fail(f"{label} is missing: {values!r}")
    if len(set(values.values())) != 1:
        _fail(f"{label} mismatch: {values!r}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _set_mismatch(label: str, expected: set[str], actual: set[str]) -> str:
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    return f"{label} mismatch: missing={missing[:10]}, extra={extra[:10]}"


def _fail(message: str):
    raise DatasetReleaseError(f"{FAILURE_BANNER}: {message}")


def _write_report(path_value: str | None, report: dict[str, Any]) -> None:
    if not path_value:
        return
    path = Path(path_value).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify or stage an immutable DA-DAKA dataset release"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--dataset-root", required=True)
    verify_parser.add_argument("--mode", choices=("metadata", "full"), default="full")
    verify_parser.add_argument("--report")
    stage_parser = subparsers.add_parser("stage")
    stage_parser.add_argument("--source-root", required=True)
    stage_parser.add_argument("--destination-root", required=True)
    stage_parser.add_argument("--reuse-verified", action="store_true")
    stage_parser.add_argument("--report")
    for command_parser in (verify_parser, stage_parser):
        command_parser.add_argument(
            "--expected-version",
            default=os.environ.get("DA_DAKA_DATASET_VERSION", DEFAULT_DATASET_VERSION),
        )
        command_parser.add_argument(
            "--expected-fingerprint",
            default=os.environ.get(
                "DA_DAKA_DATASET_FINGERPRINT", DEFAULT_DATASET_FINGERPRINT
            ),
        )
    args = parser.parse_args()
    try:
        if args.command == "verify":
            report = verify_dataset_release(
                args.dataset_root,
                expected_version=args.expected_version,
                expected_fingerprint=args.expected_fingerprint,
                mode=args.mode,
            )
        else:
            report = stage_dataset_release(
                args.source_root,
                args.destination_root,
                expected_version=args.expected_version,
                expected_fingerprint=args.expected_fingerprint,
                reuse_verified=args.reuse_verified,
            )
        _write_report(args.report, report)
        print(json.dumps(report, indent=2, sort_keys=True))
    except DatasetReleaseError as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    main()
