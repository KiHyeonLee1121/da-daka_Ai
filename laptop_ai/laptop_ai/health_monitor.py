"""Rate-limited runtime counters and health summaries."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time


@dataclass(slots=True)
class RuntimeMetrics:
    received_frames: int = 0
    processed_frames: int = 0
    dropped_frames: int = 0
    reconnects: int = 0
    detections: int = 0
    udp_sent: int = 0
    udp_failures: int = 0
    last_frame_id: int = 0
    last_inference_ms: float = 0.0
    last_end_to_end_ms: float = 0.0
    last_confidence: float = 0.0


class HealthMonitor:
    def __init__(self, summary_interval_s: float) -> None:
        self.metrics = RuntimeMetrics()
        self.summary_interval_s = summary_interval_s
        self._started_s = time.monotonic()
        self._last_summary_s = self._started_s

    def maybe_log(self, logger: logging.Logger, video_state: str) -> None:
        now = time.monotonic()
        if now - self._last_summary_s < self.summary_interval_s:
            return
        elapsed = max(now - self._started_s, 1e-6)
        logger.info(
            "health video=%s frame=%d fps=%.1f infer_ms=%.1f e2e_est_ms=%.1f detected=%s "
            "confidence=%.3f udp_ok=%d udp_fail=%d reconnects=%d dropped=%d",
            video_state,
            self.metrics.last_frame_id,
            self.metrics.processed_frames / elapsed,
            self.metrics.last_inference_ms,
            self.metrics.last_end_to_end_ms,
            self.metrics.last_confidence > 0.0,
            self.metrics.last_confidence,
            self.metrics.udp_sent,
            self.metrics.udp_failures,
            self.metrics.reconnects,
            self.metrics.dropped_frames,
        )
        self._last_summary_s = now
