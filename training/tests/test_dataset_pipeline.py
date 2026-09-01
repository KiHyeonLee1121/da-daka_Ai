"""Synthetic tests for COCO/CVAT ingestion, validation and derived masks."""

import json
import shutil
from zipfile import ZipFile

import cv2
import numpy as np
import pytest
from da_daka_training.dataset_builder import (
    DatasetValidationError,
    build_master_dataset,
)
from da_daka_training.release import (
    DatasetReleaseError,
    stage_dataset_release,
    verify_dataset_release,
)
from da_daka_training.sources import DatasetSourceError, load_source


def _image_bytes(value):
    image = np.full((40, 60, 3), value, dtype=np.uint8)
    ok, encoded = cv2.imencode('.png', image)
    assert ok
    return encoded.tobytes()


def _coco_source(root, value, *, dirt_polygons=(), invalid_bbox=False, missing=False):
    root.mkdir()
    (root / 'images/default').mkdir(parents=True)
    if not missing:
        (root / 'images/default/same.png').write_bytes(_image_bytes(value))
    panel_bbox = [5, 5, 70 if invalid_bbox else 50, 30]
    annotations = [
        {
            'id': 900,
            'image_id': 77,
            'category_id': 42,
            'bbox': panel_bbox,
            'area': panel_bbox[2] * panel_bbox[3],
            'segmentation': [],
            'iscrowd': 0,
        }
    ]
    for index, polygon in enumerate(dirt_polygons, 1):
        points = np.asarray(polygon, dtype=np.float32).reshape(-1, 2)
        x, y, width, height = cv2.boundingRect(points)
        annotations.append(
            {
                'id': 900 + index,
                'image_id': 77,
                'category_id': 99,
                'bbox': [x, y, width, height],
                'area': float(abs(cv2.contourArea(points))),
                'segmentation': [list(polygon)],
                'iscrowd': 0,
            }
        )
    coco = {
        'images': [{'id': 77, 'file_name': 'same.png', 'width': 60, 'height': 40}],
        'annotations': annotations,
        'categories': [
            {'id': 42, 'name': 'Solar Panel'},
            {'id': 99, 'name': 'DIRT'},
        ],
    }
    (root / 'annotations').mkdir()
    (root / 'annotations/instances_default.json').write_text(json.dumps(coco))
    return root


def _config(tmp_path, sources, output='master'):
    return {
        'output_dir': str(tmp_path / output),
        'category_aliases': {'Solar Panel': 'solar_panel'},
        'sources': [
            {'path': str(path), 'source_task': f'task-{index}'}
            for index, path in enumerate(sources, 1)
        ],
        'split': {'seed': 'test-seed', 'ratios': [0.7, 0.15, 0.15]},
    }


def test_coco_merge_remaps_categories_ids_and_filenames(tmp_path):
    sources = [_coco_source(tmp_path / f'source-{i}', i * 40) for i in range(1, 4)]
    output = build_master_dataset(_config(tmp_path, sources))
    coco = json.loads((output / 'annotations/master.json').read_text())
    manifest = json.loads((output / 'dataset_manifest.json').read_text())
    assert [image['id'] for image in coco['images']] == [1, 2, 3]
    assert [annotation['id'] for annotation in coco['annotations']] == [1, 2, 3]
    assert [annotation['image_id'] for annotation in coco['annotations']] == [1, 2, 3]
    assert {annotation['category_id'] for annotation in coco['annotations']} == {1}
    assert len({image['file_name'] for image in coco['images']}) == 3
    assert 'same.png' in manifest['filename_collisions']
    assert set(manifest['counts']['by_split']) == {'train', 'validation', 'test'}


def test_duplicate_image_sha_fails_closed(tmp_path):
    sources = [_coco_source(tmp_path / f'source-{i}', 40) for i in range(1, 4)]
    with pytest.raises(DatasetValidationError, match='duplicate image SHA'):
        build_master_dataset(_config(tmp_path, sources))


def test_missing_image_is_rejected(tmp_path):
    source = _coco_source(tmp_path / 'source', 20, missing=True)
    with pytest.raises(DatasetSourceError, match='resolves to 0'):
        load_source(source)


def test_declared_image_dimensions_must_match_decoded_media(tmp_path):
    sources = [_coco_source(tmp_path / f'source-{i}', i * 20) for i in range(1, 4)]
    path = sources[0] / 'annotations/instances_default.json'
    coco = json.loads(path.read_text())
    coco['images'][0]['width'] = 600
    path.write_text(json.dumps(coco))
    with pytest.raises(DatasetValidationError, match='metadata mismatch'):
        build_master_dataset(_config(tmp_path, sources))


def test_orphan_annotation_is_rejected(tmp_path):
    source = _coco_source(tmp_path / 'source', 20)
    path = source / 'annotations/instances_default.json'
    coco = json.loads(path.read_text())
    coco['annotations'][0]['image_id'] = 999
    path.write_text(json.dumps(coco))
    with pytest.raises(DatasetSourceError, match='orphan'):
        load_source(source)


def test_invalid_bbox_and_polygon_are_rejected(tmp_path):
    bad_bbox = _coco_source(tmp_path / 'bad-bbox', 10, invalid_bbox=True)
    valid_2 = _coco_source(tmp_path / 'valid-2', 20)
    valid_3 = _coco_source(tmp_path / 'valid-3', 30)
    with pytest.raises(DatasetValidationError, match='bbox'):
        build_master_dataset(_config(tmp_path, [bad_bbox, valid_2, valid_3], 'bad-out'))

    bad_polygon = _coco_source(
        tmp_path / 'bad-polygon',
        40,
        dirt_polygons=((10, 10, 20, 20),),
    )
    with pytest.raises(DatasetValidationError, match='polygon'):
        build_master_dataset(
            _config(tmp_path, [bad_polygon, valid_2, valid_3], 'bad-poly-out')
        )


def test_clean_zero_mask_and_multiple_dirt_polygons(tmp_path):
    clean_1 = _coco_source(tmp_path / 'clean-1', 20)
    dirty = _coco_source(
        tmp_path / 'dirty',
        40,
        dirt_polygons=(
            (10, 10, 18, 10, 18, 18, 10, 18),
            (35, 20, 42, 20, 42, 27, 35, 27),
        ),
    )
    clean_2 = _coco_source(tmp_path / 'clean-2', 60)
    output = build_master_dataset(_config(tmp_path, [clean_1, dirty, clean_2]))
    samples = [
        json.loads(line) for line in
        (output / 'dirt_segmentation/samples.jsonl').read_text().splitlines()
    ]
    assert len(samples) == 3
    clean_sample = next(item for item in samples if item['clean_dirty'] == 'clean')
    clean_mask = cv2.imread(
        str(output / 'dirt_segmentation' / clean_sample['mask']),
        cv2.IMREAD_GRAYSCALE,
    )
    assert np.count_nonzero(clean_mask) == 0
    dirty_sample = next(item for item in samples if item['clean_dirty'] == 'dirty')
    dirty_mask = cv2.imread(
        str(output / 'dirt_segmentation' / dirty_sample['mask']),
        cv2.IMREAD_GRAYSCALE,
    )
    component_count, _labels = cv2.connectedComponents((dirty_mask > 0).astype(np.uint8))
    assert component_count - 1 == 2


def test_cvat_task_backup_rectangle_and_polygon_are_ingested(tmp_path):
    backup = tmp_path / 'task_backup.zip'
    task = {
        'name': 'backup-task',
        'version': '1.0',
        'labels': [{'name': 'solar_panel'}, {'name': 'dirt'}],
        'data': {},
        'jobs': [{'start_frame': 0, 'stop_frame': 0, 'files': ['frame.png']}],
    }
    annotations = [
        {
            'tags': [],
            'tracks': [],
            'shapes': [
                {
                    'frame': 0, 'label': 'solar_panel',
                    'type': 'rectangle', 'points': [5, 5, 55, 35],
                },
                {
                    'frame': 0, 'label': 'dirt', 'type': 'polygon',
                    'points': [10, 10, 20, 10, 20, 20, 10, 20],
                },
            ],
        }
    ]
    with ZipFile(backup, 'w') as archive:
        archive.writestr('task.json', json.dumps(task))
        archive.writestr('annotations.json', json.dumps(annotations))
        archive.writestr('data/frame.png', _image_bytes(30))
    imported = load_source(backup)
    assert imported.source_task == 'backup-task'
    assert [item.category_name for item in imported.images[0].annotations] == [
        'solar_panel', 'dirt'
    ]


def test_dataset_fingerprint_is_stable_after_source_relocation(tmp_path):
    originals = [
        _coco_source(tmp_path / f'original-{index}', index * 30)
        for index in range(1, 4)
    ]
    relocated_root = tmp_path / 'relocated'
    relocated_root.mkdir()
    relocated = []
    for source in originals:
        target = relocated_root / source.name
        shutil.copytree(source, target)
        relocated.append(target)
    first = build_master_dataset(_config(tmp_path, originals, 'first-master'))
    second = build_master_dataset(_config(tmp_path, relocated, 'second-master'))
    first_manifest = json.loads((first / 'dataset_manifest.json').read_text())
    second_manifest = json.loads((second / 'dataset_manifest.json').read_text())
    assert (
        first_manifest['dataset_fingerprint']
        == second_manifest['dataset_fingerprint']
    )


def test_built_release_passes_full_identity_and_inventory_verification(tmp_path):
    sources = [_coco_source(tmp_path / f'source-{i}', i * 40) for i in range(1, 4)]
    output = build_master_dataset(_config(tmp_path, sources))
    manifest = json.loads((output / 'dataset_manifest.json').read_text())
    report = verify_dataset_release(
        output,
        expected_version=manifest['dataset_version'],
        expected_fingerprint=manifest['dataset_fingerprint'],
        mode='full',
    )
    assert report['status'] == 'VERIFIED'
    assert report['counts']['master_images'] == 3


def test_release_verifier_fails_closed_for_missing_uploaded_mask(tmp_path):
    sources = [_coco_source(tmp_path / f'source-{i}', i * 40) for i in range(1, 4)]
    output = build_master_dataset(_config(tmp_path, sources))
    manifest = json.loads((output / 'dataset_manifest.json').read_text())
    sample = json.loads(
        (output / 'dirt_segmentation/samples.jsonl').read_text().splitlines()[0]
    )
    (output / 'dirt_segmentation' / sample['mask']).unlink()
    with pytest.raises(DatasetReleaseError, match='DATASET INCOMPLETE OR WRONG RELEASE'):
        verify_dataset_release(
            output,
            expected_version=manifest['dataset_version'],
            expected_fingerprint=manifest['dataset_fingerprint'],
            mode='metadata',
        )


def test_full_release_verifier_rejects_corrupted_derived_roi_content(tmp_path):
    sources = [_coco_source(tmp_path / f"source-{i}", i * 40) for i in range(1, 4)]
    output = build_master_dataset(_config(tmp_path, sources))
    manifest = json.loads((output / "dataset_manifest.json").read_text())
    sample = json.loads(
        (output / "dirt_segmentation/samples.jsonl").read_text().splitlines()[0]
    )
    roi_path = output / "dirt_segmentation" / sample["image"]
    roi = cv2.imread(str(roi_path), cv2.IMREAD_COLOR)
    roi[0, 0] = (roi[0, 0].astype(np.uint16) + 1).clip(0, 255).astype(np.uint8)
    assert cv2.imwrite(str(roi_path), roi)
    with pytest.raises(DatasetReleaseError, match="ROI image content mismatch"):
        verify_dataset_release(
            output,
            expected_version=manifest["dataset_version"],
            expected_fingerprint=manifest["dataset_fingerprint"],
            mode="full",
        )


def test_release_staging_preflights_then_verifies_local_copy(tmp_path):
    sources = [_coco_source(tmp_path / f'source-{i}', i * 40) for i in range(1, 4)]
    output = build_master_dataset(_config(tmp_path, sources))
    manifest = json.loads((output / 'dataset_manifest.json').read_text())
    destination = tmp_path / 'local-ssd-dataset'
    report = stage_dataset_release(
        output,
        destination,
        expected_version=manifest['dataset_version'],
        expected_fingerprint=manifest['dataset_fingerprint'],
    )
    assert report['status'] == 'STAGED_AND_VERIFIED'
    assert destination.is_dir()
    assert report['destination_verification']['verification_mode'] == 'full'
