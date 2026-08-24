"""Build a validated, fingerprinted Master COCO dataset deterministically."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Mapping

import cv2
import numpy as np

from da_daka_training import CATEGORY_CONTRACT
from da_daka_training.derived import build_derived_datasets
from da_daka_training.sources import (
    ImportedAnnotation,
    load_source,
)
from da_daka_training.split import grouped_split


class DatasetValidationError(ValueError):
    """Input data violates the DA-DAKA annotation or geometry contract."""


def build_master_dataset(config: Mapping[str, Any]) -> Path:
    """Build Master COCO, provenance and split files without altering sources."""
    sources_config = config.get('sources')
    if not isinstance(sources_config, list) or not sources_config:
        raise DatasetValidationError('config.sources must be a non-empty list')
    output = Path(str(config.get('output_dir', ''))).expanduser().resolve()
    if not str(config.get('output_dir', '')).strip():
        raise DatasetValidationError('output_dir cannot be empty')
    if output.exists():
        raise DatasetValidationError(
            f'output already exists; source-safe builds never overwrite: {output}'
        )
    duplicate_policy = str(config.get('duplicate_policy', 'error')).lower()
    if duplicate_policy not in {'error', 'keep_first'}:
        raise DatasetValidationError('duplicate_policy must be error or keep_first')
    aliases = _category_aliases(config.get('category_aliases'))

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.da-daka-dataset-', dir=output.parent))
    try:
        images_directory = staging / 'images'
        annotations_directory = staging / 'annotations'
        images_directory.mkdir()
        annotations_directory.mkdir()
        coco_images = []
        coco_annotations = []
        provenance = []
        source_records = []
        annotation_id = 1
        seen_sha: dict[str, str] = {}
        filename_sources: dict[str, list[str]] = defaultdict(list)
        duplicate_images = []

        for source_index, source_config in enumerate(sources_config, 1):
            if not isinstance(source_config, dict) or 'path' not in source_config:
                raise DatasetValidationError('each source needs a path')
            imported = load_source(
                source_config['path'],
                source_type=str(source_config.get('type', 'auto')),
                source_task=source_config.get('source_task'),
            )
            source_slug = _slug(imported.source_task) or f'source-{source_index:03d}'
            source_records.append(
                {
                    'source_task': imported.source_task,
                    'source_path': imported.source_path,
                    'source_sha256': imported.source_sha256,
                    'source_type': str(source_config.get('type', 'auto')),
                    'image_count': len(imported.images),
                }
            )
            group_map = _load_group_map(source_config.get('group_map'))
            group_regex = _compile_group_regex(source_config.get('group_regex'))
            for source_image_index, imported_image in enumerate(imported.images, 1):
                filename_sources[Path(imported_image.original_filename).name].append(
                    imported.source_task
                )
                image_sha = hashlib.sha256(imported_image.content).hexdigest()
                if image_sha in seen_sha:
                    duplicate_images.append(
                        {
                            'sha256': image_sha,
                            'first': seen_sha[image_sha],
                            'duplicate': (
                                f'{imported.source_task}:{imported_image.original_filename}'
                            ),
                        }
                    )
                    if duplicate_policy == 'error':
                        raise DatasetValidationError(
                            f'duplicate image SHA-256 {image_sha}: '
                            f'{seen_sha[image_sha]} and '
                            f'{imported.source_task}:{imported_image.original_filename}'
                        )
                    continue
                seen_sha[image_sha] = (
                    f'{imported.source_task}:{imported_image.original_filename}'
                )
                height, width = _decode_and_validate_dimensions(imported_image)
                normalized_name = _normalized_filename(
                    source_slug,
                    source_image_index,
                    imported_image.original_filename,
                    image_sha,
                )
                target_path = images_directory / normalized_name
                target_path.write_bytes(imported_image.content)
                image_id = len(coco_images) + 1
                normalized_annotations = [
                    _normalize_annotation(annotation, width, height, aliases)
                    for annotation in imported_image.annotations
                ]
                panel_count = sum(
                    item['category_id'] == CATEGORY_CONTRACT['solar_panel']
                    for item in normalized_annotations
                )
                if panel_count == 0:
                    raise DatasetValidationError(
                        f'{imported.source_task}:{imported_image.original_filename} '
                        'has no solar_panel rectangle'
                    )
                dirt_count = sum(
                    item['category_id'] == CATEGORY_CONTRACT['dirt']
                    for item in normalized_annotations
                )
                coco_images.append(
                    {
                        'id': image_id,
                        'file_name': f'images/{normalized_name}',
                        'width': width,
                        'height': height,
                    }
                )
                for annotation in normalized_annotations:
                    coco_annotations.append(
                        {
                            'id': annotation_id,
                            'image_id': image_id,
                            **annotation,
                        }
                    )
                    annotation_id += 1
                groups = _group_metadata(
                    source_config,
                    group_map,
                    group_regex,
                    imported.source_task,
                    imported_image.original_filename,
                )
                provenance.append(
                    {
                        'sample_id': str(image_id),
                        'image_id': image_id,
                        'source_task': imported.source_task,
                        'source_path': imported.source_path,
                        'original_filename': imported_image.original_filename,
                        'normalized_filename': normalized_name,
                        'sha256': image_sha,
                        'capture_session': groups['capture_session'],
                        'burst_group': groups['burst_group'],
                        'panel_group': groups['panel_group'],
                        'split_group': groups['split_group'],
                        'panel_instances': panel_count,
                        'clean_dirty': 'dirty' if dirt_count else 'clean',
                        'dirt_instances': dirt_count,
                    }
                )

        collisions = {
            filename: tasks for filename, tasks in sorted(filename_sources.items())
            if len(tasks) > 1
        }
        split_config = config.get('split', {})
        if not isinstance(split_config, dict):
            raise DatasetValidationError('split must be an object')
        ratios = tuple(float(value) for value in split_config.get(
            'ratios', [0.70, 0.15, 0.15]
        ))
        assignment = grouped_split(
            provenance,
            seed=str(split_config.get('seed', 'da-daka-v1')),
            ratios=ratios,
        )
        for item in provenance:
            item['split'] = assignment[item['sample_id']]

        canonical = {
            'categories': CATEGORY_CONTRACT,
            # Absolute ingest paths are useful provenance, but they are not
            # dataset content.  Excluding them makes a rebuilt dataset keep
            # the same fingerprint after the source bundle is relocated.
            'sources': [
                {key: value for key, value in record.items() if key != 'source_path'}
                for record in source_records
            ],
            'images': coco_images,
            'annotations': coco_annotations,
            'provenance': [
                {key: value for key, value in item.items() if key != 'source_path'}
                for item in provenance
            ],
            'split_policy': {
                'unit_priority': [
                    'panel_group',
                    'burst_group',
                    'capture_session',
                    'source_task',
                ],
                'seed': str(split_config.get('seed', 'da-daka-v1')),
                'ratios': ratios,
            },
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                canonical,
                sort_keys=True,
                separators=(',', ':'),
                ensure_ascii=False,
            ).encode('utf-8')
        ).hexdigest()
        dataset_version = str(
            config.get('dataset_version') or f'da-daka-{fingerprint[:16]}'
        )
        coco = {
            'info': {
                'description': 'DA-DAKA validated master dataset',
                'version': dataset_version,
                'dataset_fingerprint': fingerprint,
            },
            'licenses': [],
            'images': coco_images,
            'annotations': coco_annotations,
            'categories': [
                {'id': category_id, 'name': name, 'supercategory': 'solar_panel'}
                for name, category_id in CATEGORY_CONTRACT.items()
            ],
        }
        _write_json(annotations_directory / 'master.json', coco)
        for split in ('train', 'validation', 'test'):
            image_ids = {
                int(item['image_id']) for item in provenance
                if item['split'] == split
            }
            split_coco = {
                **{
                    key: value for key, value in coco.items()
                    if key not in {'images', 'annotations'}
                },
                'images': [item for item in coco_images if item['id'] in image_ids],
                'annotations': [
                    item for item in coco_annotations if item['image_id'] in image_ids
                ],
            }
            _write_json(annotations_directory / f'{split}.json', split_coco)
        _write_json(staging / 'provenance.json', provenance)
        manifest = {
            'manifest_version': 1,
            'dataset_version': dataset_version,
            'dataset_fingerprint': fingerprint,
            'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'git_commit': _git_commit(),
            'sources': source_records,
            'split_policy': canonical['split_policy'],
            'counts': {
                'images': len(coco_images),
                'annotations': len(coco_annotations),
                'clean_images': sum(item['clean_dirty'] == 'clean' for item in provenance),
                'dirty_images': sum(item['clean_dirty'] == 'dirty' for item in provenance),
                'by_split': dict(Counter(item['split'] for item in provenance)),
            },
            'filename_collisions': collisions,
            'duplicate_images': duplicate_images,
            'category_contract': CATEGORY_CONTRACT,
        }
        _write_json(staging / 'dataset_manifest.json', manifest)
        manifest['derived_counts'] = build_derived_datasets(staging)
        _write_json(staging / 'dataset_manifest.json', manifest)
        _write_json(
            staging / 'dataset_summary.json',
            {
                'dataset_version': dataset_version,
                'dataset_fingerprint': fingerprint,
                'counts': manifest['counts'],
                'derived_counts': manifest['derived_counts'],
                'filename_collision_count': len(collisions),
                'duplicate_image_count': len(duplicate_images),
            },
        )
        os.replace(staging, output)
        return output
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _normalize_annotation(
    annotation: ImportedAnnotation,
    image_width: int,
    image_height: int,
    aliases: Mapping[str, str],
) -> dict[str, Any]:
    name_key = _category_key(annotation.category_name)
    category_name = aliases.get(name_key, name_key)
    if category_name not in CATEGORY_CONTRACT:
        raise DatasetValidationError(
            f'unknown category {annotation.category_name!r}; expected solar_panel or dirt'
        )
    x, y, width, height = annotation.bbox
    values = (x, y, width, height)
    if any(not math.isfinite(value) for value in values):
        raise DatasetValidationError('bbox/area values must be finite')
    if width <= 0.0 or height <= 0.0:
        raise DatasetValidationError('bbox values must be positive')
    epsilon = 1e-4
    if (
        x < -epsilon
        or y < -epsilon
        or x + width > image_width + epsilon
        or y + height > image_height + epsilon
    ):
        raise DatasetValidationError(
            f'bbox {(x, y, width, height)} exceeds image {image_width}x{image_height}'
        )
    segmentation = [list(polygon) for polygon in annotation.segmentation]
    if category_name == 'solar_panel':
        if segmentation:
            raise DatasetValidationError('solar_panel must be a Rectangle, not a polygon')
        area = width * height
    else:
        if not segmentation:
            raise DatasetValidationError('dirt must have Polygon segmentation')
        area = 0.0
        for polygon in segmentation:
            if len(polygon) < 6 or len(polygon) % 2:
                raise DatasetValidationError('dirt polygon needs at least three points')
            if any(not math.isfinite(float(value)) for value in polygon):
                raise DatasetValidationError('polygon points must be finite')
            xs = polygon[0::2]
            ys = polygon[1::2]
            if (
                min(xs) < -epsilon
                or min(ys) < -epsilon
                or max(xs) > image_width + epsilon
                or max(ys) > image_height + epsilon
            ):
                raise DatasetValidationError('dirt polygon exceeds image bounds')
            points = np.asarray(polygon, dtype=np.float32).reshape(-1, 2)
            polygon_area = float(abs(cv2.contourArea(points)))
            if polygon_area <= 0.0:
                raise DatasetValidationError('dirt polygon has zero area')
            area += polygon_area
    return {
        'category_id': CATEGORY_CONTRACT[category_name],
        'bbox': [float(x), float(y), float(width), float(height)],
        'area': float(area),
        'segmentation': segmentation,
        'iscrowd': 0,
    }


def _decode_and_validate_dimensions(imported_image) -> tuple[int, int]:
    image = cv2.imdecode(
        np.frombuffer(imported_image.content, dtype=np.uint8),
        cv2.IMREAD_COLOR,
    )
    if image is None:
        raise DatasetValidationError(
            f'cannot decode image {imported_image.original_filename!r}'
        )
    height, width = image.shape[:2]
    if (
        width != imported_image.declared_width
        or height != imported_image.declared_height
    ):
        raise DatasetValidationError(
            f'image metadata mismatch for {imported_image.original_filename}: '
            f'declared {imported_image.declared_width}x{imported_image.declared_height}, '
            f'actual {width}x{height}'
        )
    return height, width


def _category_aliases(raw: Any) -> dict[str, str]:
    aliases = {'solar_panel': 'solar_panel', 'dirt': 'dirt'}
    if raw is None:
        return aliases
    if not isinstance(raw, dict):
        raise DatasetValidationError('category_aliases must be an object')
    for source, target in raw.items():
        normalized_target = _category_key(str(target))
        if normalized_target not in CATEGORY_CONTRACT:
            raise DatasetValidationError(f'invalid category alias target: {target!r}')
        aliases[_category_key(str(source))] = normalized_target
    return aliases


def _category_key(value: str) -> str:
    return re.sub(r'_+', '_', re.sub(r'[^a-z0-9]+', '_', value.strip().lower())).strip('_')


def _slug(value: str) -> str:
    return _category_key(value)[:48]


def _normalized_filename(source_slug, index, original, sha):
    original_path = Path(original)
    stem = _slug(original_path.stem) or 'image'
    suffix = original_path.suffix.lower()
    if suffix == '.jpeg':
        suffix = '.jpg'
    return f'{source_slug}__{index:06d}__{stem}__{sha[:12]}{suffix}'


def _load_group_map(path_value: Any) -> Mapping[str, Any]:
    if not path_value:
        return {}
    path = Path(str(path_value)).expanduser().resolve()
    raw = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(raw, dict):
        raise DatasetValidationError('group_map must be a JSON object')
    return raw


def _compile_group_regex(value: Any):
    if not value:
        return None
    try:
        return re.compile(str(value))
    except re.error as exc:
        raise DatasetValidationError(f'invalid group_regex: {exc}') from exc


def _group_metadata(config, group_map, group_regex, source_task, filename):
    values = {
        'capture_session': str(config.get('capture_session') or source_task),
        'burst_group': str(config.get('burst_group') or ''),
        'panel_group': str(config.get('panel_group') or ''),
        'split_group': str(config.get('split_group') or ''),
    }
    mapped = group_map.get(filename) or group_map.get(Path(filename).name) or {}
    if mapped and not isinstance(mapped, dict):
        raise DatasetValidationError(f'group_map entry for {filename!r} is invalid')
    for key in values:
        if mapped.get(key):
            values[key] = str(mapped[key])
    if group_regex is not None:
        match = group_regex.search(filename)
        if match:
            for key, value in match.groupdict().items():
                if key in values and value:
                    values[key] = value
    values['split_group'] = values['split_group'] or (
        values['panel_group']
        or values['burst_group']
        or values['capture_session']
        or source_task
    )
    return values


def _git_commit() -> str:
    try:
        return subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return 'unknown'


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + '\n',
        encoding='utf-8',
    )
