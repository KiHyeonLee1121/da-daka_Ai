from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


BBox = tuple[int, int, int, int]
Point = tuple[int, int]


@dataclass(slots=True)
class DirtCandidate:
    centroid: Point
    bbox: BBox
    area: float
    confidence: float
    score: float


@dataclass(slots=True)
class DirtDetectionResult:
    found: bool
    centroid: Point | None = None
    bbox: BBox | None = None
    area: float = 0.0
    confidence: float = 0.0
    mask: Any | None = None
    candidates: list[DirtCandidate] = field(default_factory=list)

    @classmethod
    def empty(cls, mask: Any | None = None) -> "DirtDetectionResult":
        return cls(found=False, mask=mask)


class BaseDirtDetector(ABC):
    @abstractmethod
    def detect(self, frame: Any, roi: BBox | None = None) -> DirtDetectionResult:
        """Detect dirt candidates in a BGR frame.

        Coordinates returned by implementations must be in full-frame pixels,
        even when an ROI is supplied.
        """
