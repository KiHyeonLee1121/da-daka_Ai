from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from utils.time_utils import timestamp_for_filename, timestamp_iso


FIELDNAMES = [
    "timestamp",
    "state",
    "detection_found",
    "centroid_x",
    "centroid_y",
    "bbox_x",
    "bbox_y",
    "bbox_w",
    "bbox_h",
    "area",
    "confidence",
    "error_x",
    "error_y",
    "lidar_distance_m",
    "lidar_valid",
    "command",
    "vx",
    "vy",
    "vz",
    "yaw_rate",
    "spray_event",
    "retry_count",
    "detection_streak",
    "spray_count",
    "message",
]


class MissionLogger:
    def __init__(self, save_logs: bool, logs_dir: str | Path = "logs"):
        self.save_logs = save_logs
        self.logs_dir = Path(logs_dir)
        self.csv_file = None
        self.jsonl_file = None
        self.csv_writer = None
        self.csv_path: Path | None = None
        self.jsonl_path: Path | None = None

        if save_logs:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            stamp = timestamp_for_filename()
            self.csv_path = self.logs_dir / f"mission_{stamp}.csv"
            self.jsonl_path = self.logs_dir / f"mission_{stamp}.jsonl"
            self.csv_file = self.csv_path.open("w", encoding="utf-8", newline="")
            self.jsonl_file = self.jsonl_path.open("w", encoding="utf-8")
            self.csv_writer = csv.DictWriter(self.csv_file, fieldnames=FIELDNAMES)
            self.csv_writer.writeheader()

    def log(self, row: dict[str, Any]) -> None:
        if not self.save_logs:
            return
        clean = {field: self._stringify(row.get(field, "")) for field in FIELDNAMES}
        assert self.csv_writer is not None
        assert self.csv_file is not None
        assert self.jsonl_file is not None
        self.csv_writer.writerow(clean)
        self.csv_file.flush()
        json.dump(row, self.jsonl_file, ensure_ascii=False, default=str)
        self.jsonl_file.write("\n")
        self.jsonl_file.flush()

    def close(self) -> None:
        if self.csv_file is not None:
            self.csv_file.close()
        if self.jsonl_file is not None:
            self.jsonl_file.close()

    @staticmethod
    def _stringify(value: Any) -> Any:
        if hasattr(value, "value"):
            return value.value
        if isinstance(value, float):
            return f"{value:.6f}"
        return value


def make_log_row(
    state: Any,
    detection: Any,
    target: Any,
    lidar: Any,
    command: Any,
    spray_event: Any,
    retry_count: int,
    detection_streak: int = 0,
    spray_count: int = 0,
    message: str = "",
) -> dict[str, Any]:
    bbox = detection.bbox if getattr(detection, "bbox", None) else (None, None, None, None)
    centroid = detection.centroid if getattr(detection, "centroid", None) else (None, None)
    return {
        "timestamp": timestamp_iso(),
        "state": getattr(state, "value", state),
        "detection_found": bool(getattr(detection, "found", False)),
        "centroid_x": centroid[0],
        "centroid_y": centroid[1],
        "bbox_x": bbox[0],
        "bbox_y": bbox[1],
        "bbox_w": bbox[2],
        "bbox_h": bbox[3],
        "area": getattr(detection, "area", 0.0),
        "confidence": getattr(detection, "confidence", 0.0),
        "error_x": getattr(target, "error_x", None),
        "error_y": getattr(target, "error_y", None),
        "lidar_distance_m": getattr(lidar, "distance_m", None),
        "lidar_valid": getattr(lidar, "valid", False),
        "command": getattr(getattr(command, "command_type", None), "value", None),
        "vx": getattr(command, "vx", 0.0),
        "vy": getattr(command, "vy", 0.0),
        "vz": getattr(command, "vz", 0.0),
        "yaw_rate": getattr(command, "yaw_rate", 0.0),
        "spray_event": spray_event.backend if spray_event else "",
        "retry_count": retry_count,
        "detection_streak": detection_streak,
        "spray_count": spray_count,
        "message": message,
    }
