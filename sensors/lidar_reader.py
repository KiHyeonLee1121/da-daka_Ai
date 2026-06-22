from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import random
import time
from typing import Any


@dataclass(slots=True)
class LiDARReading:
    distance_m: float | None
    valid: bool
    timestamp: float


class DistanceStatus(str, Enum):
    TOO_CLOSE = "TOO_CLOSE"
    OK = "OK"
    TOO_FAR = "TOO_FAR"
    INVALID = "INVALID"


class BaseLiDARReader:
    def read_distance(self) -> LiDARReading:
        raise NotImplementedError

    def close(self) -> None:
        pass


class MockLiDARReader(BaseLiDARReader):
    def __init__(self, lidar_config: dict[str, Any]):
        self.distance_m = float(lidar_config.get("mock_distance_m", 1.0))
        self.noise_std = float(lidar_config.get("mock_noise_std", 0.02))

    def read_distance(self) -> LiDARReading:
        noisy = self.distance_m + random.gauss(0.0, self.noise_std)
        return LiDARReading(distance_m=max(0.0, noisy), valid=True, timestamp=time.time())


class SerialLiDARReader(BaseLiDARReader):
    """Generic line-based serial LiDAR reader placeholder.

    If the real sensor outputs a vendor-specific binary protocol, replace
    `_parse_line()` with the sensor's protocol parser.
    """

    def __init__(self, lidar_config: dict[str, Any]):
        self.port = str(lidar_config.get("port", "/dev/ttyUSB0"))
        self.baudrate = int(lidar_config.get("baudrate", 115200))
        self.timeout_s = float(lidar_config.get("timeout_s", 0.1))
        self.serial = None

    def connect(self) -> None:
        import serial

        self.serial = serial.Serial(self.port, self.baudrate, timeout=self.timeout_s)

    def read_distance(self) -> LiDARReading:
        if self.serial is None:
            self.connect()

        assert self.serial is not None
        line = self.serial.readline().decode("ascii", errors="ignore").strip()
        distance_m = self._parse_line(line)
        return LiDARReading(distance_m=distance_m, valid=distance_m is not None, timestamp=time.time())

    def close(self) -> None:
        if self.serial is not None:
            self.serial.close()
            self.serial = None

    @staticmethod
    def _parse_line(line: str) -> float | None:
        if not line:
            return None
        for token in line.replace(",", " ").split():
            try:
                value = float(token)
                # Many low-cost modules report millimeters. Treat large values as mm.
                return value / 1000.0 if value > 20.0 else value
            except ValueError:
                continue
        return None


def classify_distance(
    reading: LiDARReading,
    target_distance_m: float,
    tolerance_m: float,
) -> DistanceStatus:
    if not reading.valid or reading.distance_m is None:
        return DistanceStatus.INVALID
    if reading.distance_m < target_distance_m - tolerance_m:
        return DistanceStatus.TOO_CLOSE
    if reading.distance_m > target_distance_m + tolerance_m:
        return DistanceStatus.TOO_FAR
    return DistanceStatus.OK


def create_lidar_reader(lidar_config: dict[str, Any]) -> BaseLiDARReader:
    backend = str(lidar_config.get("backend", "mock")).lower()
    if backend == "serial":
        return SerialLiDARReader(lidar_config)
    if backend != "mock":
        raise ValueError(f"Unsupported LiDAR backend: {backend}")
    return MockLiDARReader(lidar_config)
