"""PyTorch datasets that reuse the exact runtime letterbox implementation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from da_daka_training.augmentation import augment_image_mask


def preprocess_contract(config: dict):
    """Build the subset accepted by laptop_ai.preprocessing.preprocess_bgr."""
    return SimpleNamespace(
        input_width=int(config['input_width']),
        input_height=int(config['input_height']),
        padding_value=int(config.get('padding_value', 114)),
        color=str(config.get('color', 'RGB')).upper(),
        scale=float(config.get('scale', 1.0 / 255.0)),
        mean=tuple(float(value) for value in config.get('mean', [0.0, 0.0, 0.0])),
        std=tuple(float(value) for value in config.get('std', [1.0, 1.0, 1.0])),
    )


class DirtRoiDataset:
    """Panel crop plus binary dirt mask, including all-zero clean negatives."""

    def __init__(self, root, split, config, *, augment=False):
        self.root = Path(root)
        self.split = split
        self.config = config
        self.contract = preprocess_contract(config['preprocess'])
        self.augment = augment
        self.seed = int(config.get('seed', 20260825))
        self.epoch = 0
        self.samples = [
            json.loads(line) for line in
            (self.root / 'dirt_segmentation/samples.jsonl')
            .read_text(encoding='utf-8').splitlines()
            if line.strip() and json.loads(line)['split'] == split
        ]
        if not self.samples:
            raise ValueError(f'no dirt ROI samples for split {split}')

    def set_epoch(self, epoch):
        self.epoch = int(epoch)

    def _rng(self, index):
        material = f'{self.seed}\0{self.split}\0{self.epoch}\0{index}'.encode()
        seed = int.from_bytes(hashlib.sha256(material).digest()[:8], 'big')
        return np.random.default_rng(seed)

    def __len__(self):
        return len(self.samples)

    def prepare_numpy(self, index, *, augment=None):
        from laptop_ai.preprocessing import letterbox_image, preprocess_bgr

        sample = self.samples[index]
        image = cv2.imread(
            str(self.root / 'dirt_segmentation' / sample['image']),
            cv2.IMREAD_COLOR,
        )
        mask = cv2.imread(
            str(self.root / 'dirt_segmentation' / sample['mask']),
            cv2.IMREAD_GRAYSCALE,
        )
        use_augmentation = self.augment if augment is None else augment
        if use_augmentation:
            image, mask = augment_image_mask(
                image,
                mask,
                self.config.get('augmentation', {}),
                self._rng(index),
            )
        tensor, transform = preprocess_bgr(image, self.contract)
        padded_mask, _mask_transform = letterbox_image(
            mask,
            self.contract.input_width,
            self.contract.input_height,
            padding_value=0,
            interpolation=cv2.INTER_NEAREST,
        )
        return tensor[0], (padded_mask > 0).astype(np.int64), mask > 0, transform

    def __getitem__(self, index):
        import torch

        image, mask, _original, _transform = self.prepare_numpy(index)
        return torch.from_numpy(image), torch.from_numpy(mask)


class PanelCocoDataset:
    """Single-class detection dataset with runtime-identical letterboxing."""

    def __init__(self, root, split, config, *, augment=False):
        self.root = Path(root)
        self.config = config
        self.contract = preprocess_contract(config['preprocess'])
        self.augment = augment
        self.split = split
        self.seed = int(config.get('seed', 20260825))
        self.epoch = 0
        coco = json.loads(
            (self.root / f'panel_detection/annotations/{split}.json').read_text(encoding='utf-8')
        )
        by_image = {int(item['id']): [] for item in coco['images']}
        for annotation in coco['annotations']:
            by_image[int(annotation['image_id'])].append(annotation)
        self.records = [(image, by_image[int(image['id'])]) for image in coco['images']]
        if not self.records:
            raise ValueError(f'no panel samples for split {split}')

    def set_epoch(self, epoch):
        self.epoch = int(epoch)

    def _rng(self, index):
        material = f'{self.seed}\0{self.split}\0{self.epoch}\0{index}'.encode()
        seed = int.from_bytes(hashlib.sha256(material).digest()[:8], 'big')
        return np.random.default_rng(seed)

    def __len__(self):
        return len(self.records)

    def prepare_numpy(self, index, *, augment=None):
        from laptop_ai.preprocessing import preprocess_bgr

        image_info, annotations = self.records[index]
        image = cv2.imread(
            str(self.root / 'panel_detection' / image_info['file_name']),
            cv2.IMREAD_COLOR,
        )
        use_augmentation = self.augment if augment is None else augment
        if use_augmentation:
            image, _unused = augment_image_mask(
                image,
                None,
                {
                    key: value for key, value in self.config.get('augmentation', {}).items()
                    if key != 'perspective_probability'
                },
                self._rng(index),
            )
        tensor, transform = preprocess_bgr(image, self.contract)
        boxes = []
        for annotation in annotations:
            x, y, width, height = transform.to_input_bbox(annotation['bbox'])
            boxes.append([x, y, x + width, y + height])
        return tensor[0], np.asarray(boxes, dtype=np.float32), transform

    def __getitem__(self, index):
        import torch

        image, boxes, _transform = self.prepare_numpy(index)
        target = {
            'boxes': torch.from_numpy(boxes),
            'labels': torch.ones((len(boxes),), dtype=torch.int64),
            'image_id': torch.tensor([int(self.records[index][0]['id'])]),
        }
        return torch.from_numpy(image), target


def detection_collate(batch):
    return tuple(zip(*batch))
