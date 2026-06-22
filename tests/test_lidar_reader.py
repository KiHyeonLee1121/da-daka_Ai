from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sensors.lidar_reader import BaseLiDARReader, FilteredLiDARReader, LiDARReading


class SequenceLiDARReader(BaseLiDARReader):
    def __init__(self, values: list[float | None]):
        self.values = values
        self.index = 0

    def read_distance(self) -> LiDARReading:
        value = self.values[self.index]
        self.index = min(self.index + 1, len(self.values) - 1)
        return LiDARReading(distance_m=value, valid=value is not None, timestamp=float(self.index))


def test_lidar_filter_rejects_out_of_range_distance() -> None:
    reader = FilteredLiDARReader(
        SequenceLiDARReader([3.2]),
        {"min_valid_distance_m": 0.5, "max_valid_distance_m": 2.5, "smoothing_window": 3},
    )

    reading = reader.read_distance()
    assert reading.valid is False
    assert reading.distance_m == 3.2


def test_lidar_filter_smooths_recent_valid_samples() -> None:
    reader = FilteredLiDARReader(
        SequenceLiDARReader([1.5, 1.7, 1.6]),
        {"min_valid_distance_m": 0.5, "max_valid_distance_m": 2.5, "smoothing_window": 3},
    )

    assert reader.read_distance().distance_m == 1.5
    assert reader.read_distance().distance_m == 1.6
    assert abs(reader.read_distance().distance_m - 1.6) < 1e-9


def test_lidar_filter_rejects_large_jump() -> None:
    reader = FilteredLiDARReader(
        SequenceLiDARReader([1.5, 2.2]),
        {
            "min_valid_distance_m": 0.5,
            "max_valid_distance_m": 2.5,
            "smoothing_window": 3,
            "max_jump_m": 0.3,
        },
    )

    assert reader.read_distance().valid is True
    reading = reader.read_distance()
    assert reading.valid is False
    assert reading.distance_m == 2.2
