"""Read-only adapters for CVAT Task Backup and CVAT COCO 1.0 sources."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping
from zipfile import BadZipFile, ZipFile

import cv2
import numpy as np


IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp'}


class DatasetSourceError(ValueError):
    """A source cannot be interpreted without risking annotation corruption."""


@dataclass(frozen=True)
class ImportedAnnotation:
    category_name: str
    bbox: tuple[float, float, float, float]
    segmentation: tuple[tuple[float, ...], ...]
    area: float


@dataclass(frozen=True)
class ImportedImage:
    original_filename: str
    content: bytes
    declared_width: int
    declared_height: int
    annotations: tuple[ImportedAnnotation, ...]


@dataclass(frozen=True)
class ImportedSource:
    source_task: str
    source_path: str
    source_sha256: str
    images: tuple[ImportedImage, ...]


def load_source(
    path: str | Path,
    *,
    source_type: str = 'auto',
    source_task: str | None = None,
) -> ImportedSource:
    """Detect and load one source without writing into or beside it."""
    source_path = Path(path).expanduser().resolve()
    if not source_path.exists():
        raise DatasetSourceError(f'source does not exist: {source_path}')
    kind = source_type.lower()
    if kind == 'auto':
        kind = _detect_source_type(source_path)
    if kind == 'coco':
        return _load_coco(source_path, source_task)
    if kind == 'cvat_backup':
        return _load_cvat_backup(source_path, source_task)
    raise DatasetSourceError(f'unsupported source type: {source_type!r}')


def _detect_source_type(path: Path) -> str:
    names = set(_list_names(path))
    basenames = {PurePosixPath(name).name for name in names}
    if {'task.json', 'annotations.json'}.issubset(basenames):
        return 'cvat_backup'
    if any(
        name.startswith('instances') and name.endswith('.json')
        for name in basenames
    ):
        return 'coco'
    if path.suffix.lower() == '.json':
        return 'coco'
    raise DatasetSourceError(
        'could not detect source type; set type to coco or cvat_backup'
    )


def _load_coco(path: Path, source_task: str | None) -> ImportedSource:
    names = _list_names(path)
    annotation_names = sorted(
        name for name in names
        if PurePosixPath(name).name.startswith('instances')
        and name.lower().endswith('.json')
    )
    if path.suffix.lower() == '.json':
        annotation_names = [path.name]
    if not annotation_names:
        raise DatasetSourceError('COCO source has no instances*.json')
    media_names = [
        name for name in names
        if PurePosixPath(name).suffix.lower() in IMAGE_SUFFIXES
    ]
    imported = []
    seen_image_keys = set()
    for annotation_name in annotation_names:
        coco = json.loads(_read_bytes(path, annotation_name).decode('utf-8'))
        if not isinstance(coco, dict):
            raise DatasetSourceError(f'{annotation_name} is not a COCO object')
        categories = {
            item['id']: item['name'] for item in coco.get('categories', [])
            if isinstance(item, dict) and 'id' in item and 'name' in item
        }
        images = coco.get('images')
        annotations = coco.get('annotations')
        if not isinstance(images, list) or not isinstance(annotations, list):
            raise DatasetSourceError('COCO images/annotations must be arrays')
        by_image: dict[Any, list[ImportedAnnotation]] = {
            image.get('id'): [] for image in images if isinstance(image, dict)
        }
        for annotation in annotations:
            if not isinstance(annotation, dict):
                raise DatasetSourceError('COCO annotation must be an object')
            image_id = annotation.get('image_id')
            if image_id not in by_image:
                raise DatasetSourceError(
                    f'orphan COCO annotation references image_id={image_id!r}'
                )
            category_id = annotation.get('category_id')
            if category_id not in categories:
                raise DatasetSourceError(
                    f'annotation uses unknown category_id={category_id!r}'
                )
            by_image[image_id].append(
                _coco_annotation(annotation, categories[category_id])
            )
        for image in images:
            if not isinstance(image, dict):
                raise DatasetSourceError('COCO image must be an object')
            filename = image.get('file_name')
            if not isinstance(filename, str) or not filename:
                raise DatasetSourceError('COCO image file_name is invalid')
            media_name = _resolve_media_name(filename, media_names)
            key = (annotation_name, image.get('id'))
            if key in seen_image_keys:
                raise DatasetSourceError(f'duplicate COCO image ID: {key!r}')
            seen_image_keys.add(key)
            content = _read_bytes(path, media_name)
            imported.append(
                ImportedImage(
                    original_filename=filename,
                    content=content,
                    declared_width=_positive_int(image.get('width'), 'image width'),
                    declared_height=_positive_int(image.get('height'), 'image height'),
                    annotations=tuple(by_image[image.get('id')]),
                )
            )
    task_name = source_task or path.stem
    return ImportedSource(
        source_task=task_name,
        source_path=str(path),
        source_sha256=_source_sha256(path),
        images=tuple(imported),
    )


def _coco_annotation(
    annotation: Mapping[str, Any],
    category_name: str,
) -> ImportedAnnotation:
    bbox = annotation.get('bbox')
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise DatasetSourceError('COCO annotation bbox must contain four values')
    parsed_bbox = tuple(float(value) for value in bbox)
    raw_segmentation = annotation.get('segmentation', [])
    if isinstance(raw_segmentation, dict):
        raise DatasetSourceError('RLE segmentation is not accepted for this label contract')
    if not isinstance(raw_segmentation, list):
        raise DatasetSourceError('COCO segmentation must be a polygon array')
    if raw_segmentation and all(isinstance(value, (int, float)) for value in raw_segmentation):
        raw_segmentation = [raw_segmentation]
    segmentation = tuple(
        tuple(float(value) for value in polygon)
        for polygon in raw_segmentation
    )
    area = float(annotation.get('area', parsed_bbox[2] * parsed_bbox[3]))
    return ImportedAnnotation(category_name, parsed_bbox, segmentation, area)


def _load_cvat_backup(path: Path, source_task: str | None) -> ImportedSource:
    names = _list_names(path)
    task_name = _unique_named_file(names, 'task.json')
    annotations_name = _unique_named_file(names, 'annotations.json')
    task = json.loads(_read_bytes(path, task_name).decode('utf-8'))
    jobs_annotations = json.loads(
        _read_bytes(path, annotations_name).decode('utf-8')
    )
    if not isinstance(task, dict) or not isinstance(jobs_annotations, list):
        raise DatasetSourceError('CVAT backup metadata has an invalid structure')
    root = str(PurePosixPath(task_name).parent)
    root = '' if root == '.' else root.rstrip('/') + '/'
    data_prefix = root + 'data/'
    media_names = [
        name for name in names
        if name.startswith(data_prefix)
        and PurePosixPath(name).suffix.lower() in IMAGE_SUFFIXES
    ]
    if not media_names:
        raise DatasetSourceError(
            'CVAT backup contains no original image files; lightweight backups '
            'must be paired with a COCO export that includes images'
        )
    jobs = task.get('jobs', [])
    if not isinstance(jobs, list) or len(jobs) != len(jobs_annotations):
        raise DatasetSourceError('CVAT job metadata and annotations do not align')
    frame_names = _backup_frame_names(
        path,
        names,
        root,
        media_names,
        jobs,
    )
    annotations_by_frame: dict[int, list[ImportedAnnotation]] = {
        frame: [] for frame in frame_names
    }
    for job, job_annotation in zip(jobs, jobs_annotations):
        if not isinstance(job_annotation, dict):
            raise DatasetSourceError('CVAT job annotations must be objects')
        for shape in _iter_cvat_shapes(job_annotation):
            frame = _positive_int(shape.get('frame'), 'shape frame', minimum=0)
            if frame not in frame_names:
                raise DatasetSourceError(
                    f'CVAT shape frame {frame} has no corresponding image'
                )
            annotations_by_frame[frame].append(_cvat_shape(shape))
    imported = []
    for frame in sorted(frame_names):
        media_name = frame_names[frame]
        relative_name = media_name[len(data_prefix):]
        content = _read_bytes(path, media_name)
        height, width = _decode_dimensions(content, relative_name)
        imported.append(
            ImportedImage(
                original_filename=relative_name,
                content=content,
                declared_width=width,
                declared_height=height,
                annotations=tuple(annotations_by_frame[frame]),
            )
        )
    return ImportedSource(
        source_task=source_task or str(task.get('name') or path.stem),
        source_path=str(path),
        source_sha256=_source_sha256(path),
        images=tuple(imported),
    )


def _iter_cvat_shapes(job_annotations: Mapping[str, Any]):
    for shape in job_annotations.get('shapes', []):
        if not isinstance(shape, dict):
            raise DatasetSourceError('CVAT shape must be an object')
        yield shape
    for track in job_annotations.get('tracks', []):
        if not isinstance(track, dict):
            raise DatasetSourceError('CVAT track must be an object')
        label = track.get('label')
        for shape in track.get('shapes', []):
            if not shape.get('outside', False):
                yield {**shape, 'label': label}


def _cvat_shape(shape: Mapping[str, Any]) -> ImportedAnnotation:
    label = shape.get('label')
    shape_type = str(shape.get('type', '')).lower()
    points = shape.get('points')
    if not isinstance(label, str) or not isinstance(points, list):
        raise DatasetSourceError('CVAT shape label/points are invalid')
    values = tuple(float(value) for value in points)
    if shape_type == 'rectangle':
        if len(values) != 4:
            raise DatasetSourceError('CVAT rectangle needs four coordinates')
        x1, y1, x2, y2 = values
        bbox = (min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
        return ImportedAnnotation(label, bbox, (), bbox[2] * bbox[3])
    if shape_type == 'polygon':
        if len(values) < 6 or len(values) % 2:
            raise DatasetSourceError('CVAT polygon needs at least three points')
        xs = values[0::2]
        ys = values[1::2]
        bbox = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        polygon = np.asarray(values, dtype=np.float32).reshape(-1, 2)
        area = float(abs(cv2.contourArea(polygon)))
        return ImportedAnnotation(label, bbox, (values,), area)
    raise DatasetSourceError(f'unsupported CVAT shape type: {shape_type!r}')


def _backup_frame_names(path, names, root, media_names, jobs):
    data_prefix = root + 'data/'
    resolved: dict[int, str] = {}
    if any(isinstance(job, dict) and job.get('files') for job in jobs):
        for job in jobs:
            files = job.get('files', [])
            start = int(job.get('start_frame', 0))
            frames = job.get('frames')
            frame_numbers = (
                frames if isinstance(frames, list)
                else range(start, start + len(files))
            )
            if len(files) != len(frame_numbers):
                raise DatasetSourceError('CVAT custom job files/frames do not align')
            for frame, filename in zip(frame_numbers, files):
                resolved[int(frame)] = _resolve_media_name(
                    data_prefix + str(filename), media_names
                )
        return resolved
    manifest_name = root + 'data/manifest.jsonl'
    ordered = []
    if manifest_name in names:
        for line in _read_bytes(path, manifest_name).decode('utf-8').splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if not isinstance(entry, dict) or 'name' not in entry:
                continue
            filename = str(entry['name'])
            extension = str(entry.get('extension', ''))
            if extension and not filename.endswith(extension):
                filename += extension
            ordered.append(_resolve_media_name(data_prefix + filename, media_names))
    if not ordered:
        ordered = sorted(media_names)
    start_frame = int(task_start_frame(jobs))
    return {start_frame + index: name for index, name in enumerate(ordered)}


def task_start_frame(jobs: Iterable[Mapping[str, Any]]) -> int:
    starts = [int(job.get('start_frame', 0)) for job in jobs if isinstance(job, dict)]
    return min(starts) if starts else 0


def _list_names(path: Path) -> list[str]:
    if path.is_dir():
        return [item.relative_to(path).as_posix() for item in path.rglob('*') if item.is_file()]
    if path.suffix.lower() == '.json':
        return [path.name]
    try:
        with ZipFile(path) as archive:
            names = archive.namelist()
    except BadZipFile as exc:
        raise DatasetSourceError(f'not a valid ZIP source: {path}') from exc
    for name in names:
        pure = PurePosixPath(name)
        if pure.is_absolute() or '..' in pure.parts:
            raise DatasetSourceError(f'unsafe ZIP member path: {name!r}')
    return [name for name in names if not name.endswith('/')]


def _read_bytes(path: Path, name: str) -> bytes:
    if path.is_dir():
        candidate = (path / PurePosixPath(name)).resolve()
        try:
            candidate.relative_to(path)
        except ValueError as exc:
            raise DatasetSourceError(f'unsafe source path: {name!r}') from exc
        if not candidate.is_file():
            raise DatasetSourceError(f'missing source file: {name}')
        return candidate.read_bytes()
    if path.suffix.lower() == '.json':
        if name != path.name:
            raise DatasetSourceError(f'missing source file: {name}')
        return path.read_bytes()
    with ZipFile(path) as archive:
        try:
            return archive.read(name)
        except KeyError as exc:
            raise DatasetSourceError(f'missing ZIP member: {name}') from exc


def _resolve_media_name(filename: str, media_names: Iterable[str]) -> str:
    normalized = PurePosixPath(filename).as_posix().lstrip('./')
    candidates = [
        name for name in media_names
        if name == normalized
        or name.endswith('/' + normalized)
        or PurePosixPath(name).name == PurePosixPath(normalized).name
    ]
    unique = sorted(set(candidates))
    if len(unique) != 1:
        raise DatasetSourceError(
            f'image {filename!r} resolves to {len(unique)} files: {unique}'
        )
    return unique[0]


def _unique_named_file(names: Iterable[str], basename: str) -> str:
    matches = [name for name in names if PurePosixPath(name).name == basename]
    if len(matches) != 1:
        raise DatasetSourceError(f'expected exactly one {basename}, found {matches}')
    return matches[0]


def _positive_int(value: Any, name: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DatasetSourceError(f'{name} must be an integer >= {minimum}')
    return value


def _decode_dimensions(content: bytes, filename: str) -> tuple[int, int]:
    image = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise DatasetSourceError(f'cannot decode image: {filename}')
    return image.shape[0], image.shape[1]


def _source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        return digest.hexdigest()
    for item in sorted(candidate for candidate in path.rglob('*') if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode('utf-8'))
        digest.update(hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()
