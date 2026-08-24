"""Deterministic group-level dataset splitting with leakage checks."""

from __future__ import annotations

import hashlib
from typing import Any, Iterable, Mapping


SPLITS = ('train', 'validation', 'test')


def grouped_split(
    samples: Iterable[Mapping[str, Any]],
    *,
    seed: str,
    ratios: tuple[float, float, float] = (0.70, 0.15, 0.15),
) -> dict[str, str]:
    """Assign whole groups while approximately balancing image counts."""
    if not seed:
        raise ValueError('split seed cannot be empty')
    if len(ratios) != 3 or any(value <= 0.0 for value in ratios):
        raise ValueError('split ratios must contain three positive values')
    total_ratio = sum(ratios)
    normalized = tuple(value / total_ratio for value in ratios)
    groups: dict[str, list[str]] = {}
    for sample in samples:
        sample_id = str(sample['sample_id'])
        group = str(sample['split_group'])
        if not group:
            raise ValueError(f'sample {sample_id} has no split_group')
        groups.setdefault(group, []).append(sample_id)
    if len(groups) < 3:
        raise ValueError(
            'at least three independent groups are required for train/validation/test'
        )
    ordered_groups = sorted(
        groups,
        key=lambda group: (
            hashlib.sha256(f'{seed}\0{group}'.encode('utf-8')).hexdigest(),
            group,
        ),
    )
    targets = [normalized[index] * sum(map(len, groups.values())) for index in range(3)]
    counts = [0, 0, 0]
    assignment: dict[str, str] = {}
    for index, group in enumerate(ordered_groups):
        if index < 3:
            split_index = index
        else:
            split_index = min(
                range(3),
                key=lambda value: (
                    counts[value] / targets[value],
                    counts[value],
                    value,
                ),
            )
        split = SPLITS[split_index]
        for sample_id in groups[group]:
            assignment[sample_id] = split
        counts[split_index] += len(groups[group])
    assert_no_group_leakage(samples, assignment)
    return assignment


def assert_no_group_leakage(
    samples: Iterable[Mapping[str, Any]],
    assignment: Mapping[str, str],
) -> None:
    """Raise if one capture/task/panel group crosses any split boundary."""
    group_splits: dict[str, set[str]] = {}
    for sample in samples:
        sample_id = str(sample['sample_id'])
        split = assignment.get(sample_id)
        if split not in SPLITS:
            raise ValueError(f'sample {sample_id} has no valid split')
        group_splits.setdefault(str(sample['split_group']), set()).add(split)
    leaked = {
        group: sorted(splits)
        for group, splits in group_splits.items()
        if len(splits) > 1
    }
    if leaked:
        raise ValueError(f'group split leakage detected: {leaked}')
