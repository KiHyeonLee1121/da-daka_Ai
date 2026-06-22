from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from control.mavlink_bridge import MavlinkBridge

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SprayEvent:
    requested_duration_s: float
    actual_duration_s: float
    dry_run: bool
    backend: str


class BaseSprayController:
    def spray(self, duration_s: float) -> SprayEvent:
        raise NotImplementedError

    def close(self) -> None:
        pass


class MockSprayController(BaseSprayController):
    def __init__(self, spray_config: dict[str, Any]):
        self.dry_run = bool(spray_config.get("dry_run", True))
        self.min_duration_s = float(spray_config.get("min_duration_s", 0.1))
        self.max_duration_s = float(spray_config.get("max_duration_s", 1.0))

    def spray(self, duration_s: float) -> SprayEvent:
        duration = self._clamp(duration_s)
        logger.info("[DRY-RUN] mock spray pulse requested=%.3fs actual=%.3fs", duration_s, duration)
        return SprayEvent(duration_s, duration, dry_run=True, backend="mock")

    def _clamp(self, duration_s: float) -> float:
        return max(self.min_duration_s, min(self.max_duration_s, float(duration_s)))


class GPIOSprayController(MockSprayController):
    def spray(self, duration_s: float) -> SprayEvent:
        duration = self._clamp(duration_s)
        logger.warning("GPIO spray backend is a placeholder. No GPIO output was toggled.")
        return SprayEvent(duration_s, duration, dry_run=True, backend="gpio-placeholder")


class MAVLinkSprayController(MockSprayController):
    def __init__(self, spray_config: dict[str, Any], mavlink: MavlinkBridge):
        super().__init__(spray_config)
        self.mavlink = mavlink

    def spray(self, duration_s: float) -> SprayEvent:
        duration = self._clamp(duration_s)
        self.mavlink.send_spray_trigger(duration)
        return SprayEvent(duration_s, duration, dry_run=self.mavlink.dry_run, backend="mavlink")


def create_spray_controller(spray_config: dict[str, Any], mavlink: MavlinkBridge) -> BaseSprayController:
    backend = str(spray_config.get("backend", "mock")).lower()
    if backend == "gpio":
        return GPIOSprayController(spray_config)
    if backend == "mavlink":
        return MAVLinkSprayController(spray_config, mavlink)
    if backend != "mock":
        raise ValueError(f"Unsupported spray backend: {backend}")
    return MockSprayController(spray_config)
