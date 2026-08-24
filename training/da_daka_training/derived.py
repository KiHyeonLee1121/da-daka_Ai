"""Create panel-detection COCO and panel-ROI dirt mask datasets."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
from typing import Any

import cv2
import numpy as np

from da_daka_training import CATEGORY_CONTRACT


def build_derived_datasets(master_root: str | Path) -> dict[str, int]:
    """Derive samples only after the original image-level split is fixed."""
    root = Path(master_root)
    coco = json.loads((root / 'annotations/master.json').read_text(encoding='utf-8'))
    provenance = json.loads((root / 'provenance.json').read_text(encoding='utf-8'))
    split_by_image = {
        int(item['image_id']): str(item['split']) for item in provenance
    }
    images_by_id = {int(item['id']): item for item in coco['images']}
    annotations_by_image: dict[int, list[dict[str, Any]]] = {
        image_id: [] for image_id in images_by_id
    }
    for annotation in coco['annotations']:
        annotations_by_image[int(annotation['image_id'])].append(annotation)

    panel_root = root / 'panel_detection'
    panel_images = panel_root / 'images'
    panel_annotations = panel_root / 'annotations'
    panel_images.mkdir(parents=True)
    panel_annotations.mkdir()
    for image in coco['images']:
        source = root / image['file_name']
        target = panel_images / Path(image['file_name']).name
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
    for split in ('train', 'validation', 'test'):
        image_ids = {
            image_id for image_id, value in split_by_image.items() if value == split
        }
        split_annotations = [
            annotation for annotation in coco['annotations']
            if int(annotation['image_id']) in image_ids
            and int(annotation['category_id']) == CATEGORY_CONTRACT['solar_panel']
        ]
        detection_coco = {
            'info': coco['info'],
            'licenses': coco.get('licenses', []),
            'images': [
                {**image, 'file_name': f'images/{Path(image["file_name"]).name}'}
                for image in coco['images'] if int(image['id']) in image_ids
            ],
            'annotations': [
                {**annotation, 'id': index}
                for index, annotation in enumerate(split_annotations, 1)
            ],
            'categories': [
                {
                    'id': CATEGORY_CONTRACT['solar_panel'],
                    'name': 'solar_panel',
                    'supercategory': 'solar_panel',
                }
            ],
        }
        _write_json(panel_annotations / f'{split}.json', detection_coco)

    roi_root = root / 'dirt_segmentation'
    samples = []
    dirt_category = CATEGORY_CONTRACT['dirt']
    panel_category = CATEGORY_CONTRACT['solar_panel']
    unassigned_dirt = []
    for image_id, image_info in sorted(images_by_id.items()):
        split = split_by_image[image_id]
        image = cv2.imread(str(root / image_info['file_name']), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f'cannot read master image {image_info["file_name"]}')
        height, width = image.shape[:2]
        dirt_annotations = [
            item for item in annotations_by_image[image_id]
            if int(item['category_id']) == dirt_category
        ]
        full_mask = np.zeros((height, width), dtype=np.uint8)
        dirt_masks = []
        for dirt in dirt_annotations:
            instance_mask = np.zeros_like(full_mask)
            for polygon in dirt.get('segmentation', []):
                points = np.rint(
                    np.asarray(polygon, dtype=np.float32).reshape(-1, 2)
                ).astype(np.int32)
                cv2.fillPoly(instance_mask, [points], 255)
            full_mask = cv2.bitwise_or(full_mask, instance_mask)
            dirt_masks.append((int(dirt['id']), instance_mask))
        panels = [
            item for item in annotations_by_image[image_id]
            if int(item['category_id']) == panel_category
        ]
        assigned = {annotation_id: False for annotation_id, _mask in dirt_masks}
        for panel_index, panel in enumerate(panels, 1):
            x, y, box_width, box_height = (float(value) for value in panel['bbox'])
            left = max(0, int(math.floor(x)))
            top = max(0, int(math.floor(y)))
            right = min(width, int(math.ceil(x + box_width)))
            bottom = min(height, int(math.ceil(y + box_height)))
            if right <= left or bottom <= top:
                raise ValueError(f'panel annotation {panel["id"]} has empty crop')
            crop = image[top:bottom, left:right]
            mask = full_mask[top:bottom, left:right]
            for annotation_id, instance_mask in dirt_masks:
                if np.any(instance_mask[top:bottom, left:right]):
                    assigned[annotation_id] = True
            stem = Path(image_info['file_name']).stem
            sample_name = f'{stem}__panel-{panel_index:03d}'
            image_relative = Path(split) / 'images' / f'{sample_name}.png'
            mask_relative = Path(split) / 'masks' / f'{sample_name}.png'
            image_path = roi_root / image_relative
            mask_path = roi_root / mask_relative
            image_path.parent.mkdir(parents=True, exist_ok=True)
            mask_path.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(image_path), crop):
                raise RuntimeError(f'failed to write ROI image {image_path}')
            if not cv2.imwrite(str(mask_path), mask):
                raise RuntimeError(f'failed to write ROI mask {mask_path}')
            samples.append(
                {
                    'sample_id': sample_name,
                    'source_image_id': image_id,
                    'source_panel_annotation_id': int(panel['id']),
                    'panel_instance': panel_index,
                    'split': split,
                    'image': image_relative.as_posix(),
                    'mask': mask_relative.as_posix(),
                    'crop_xywh': [left, top, right - left, bottom - top],
                    'width': right - left,
                    'height': bottom - top,
                    'clean_dirty': 'dirty' if np.any(mask) else 'clean',
                    'dirt_pixel_count': int(np.count_nonzero(mask)),
                    'dirt_area_ratio': float(np.count_nonzero(mask) / mask.size),
                }
            )
        unassigned_dirt.extend(
            annotation_id for annotation_id, is_assigned in assigned.items()
            if not is_assigned
        )
    if unassigned_dirt:
        raise ValueError(
            f'dirt polygons do not overlap any solar_panel rectangle: {unassigned_dirt}'
        )
    roi_root.mkdir(exist_ok=True)
    with (roi_root / 'samples.jsonl').open('w', encoding='utf-8') as stream:
        for sample in samples:
            stream.write(json.dumps(sample, sort_keys=True) + '\n')
    _write_json(
        roi_root / 'dataset.json',
        {
            'source_dataset_version': coco['info']['version'],
            'source_dataset_fingerprint': coco['info']['dataset_fingerprint'],
            'split_before_roi': True,
            'samples': samples,
        },
    )
    return {
        'panel_detection_images': len(coco['images']),
        'dirt_segmentation_samples': len(samples),
        'clean_roi_samples': sum(item['clean_dirty'] == 'clean' for item in samples),
        'dirty_roi_samples': sum(item['clean_dirty'] == 'dirty' for item in samples),
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + '\n',
        encoding='utf-8',
    )
