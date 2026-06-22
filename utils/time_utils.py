from __future__ import annotations

from datetime import datetime
import time


def now_s() -> float:
    return time.time()


def timestamp_for_filename(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts or now_s()).strftime("%Y%m%d_%H%M%S")


def timestamp_iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts or now_s()).isoformat(timespec="milliseconds")
