"""Reconnectable OpenCV video input with a single latest-frame buffer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
import threading
import time
from typing import Any, Callable

from laptop_ai.config import VideoConfig


logger = logging.getLogger(__name__)


class VideoState(str, Enum):
    STOPPED = "stopped"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


@dataclass(frozen=True, slots=True)
class FramePacket:
    frame_id: int
    capture_timestamp_ns: int
    received_monotonic_ns: int
    image_width: int
    image_height: int
    frame: Any


class LatestFrameBuffer:
    """Hold one frame so slow inference cannot create an old-frame queue."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._latest: FramePacket | None = None
        self._last_consumed_id = 0
        self.dropped_frames = 0

    def put(self, packet: FramePacket) -> None:
        with self._condition:
            if (
                self._latest is not None
                and self._latest.frame_id > self._last_consumed_id
            ):
                self.dropped_frames += 1
            self._latest = packet
            self._condition.notify_all()

    def get_after(self, frame_id: int, timeout_s: float) -> FramePacket | None:
        deadline = time.monotonic() + timeout_s
        with self._condition:
            while self._latest is None or self._latest.frame_id <= frame_id:
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return None
                self._condition.wait(remaining)
            self._last_consumed_id = self._latest.frame_id
            return self._latest

    @staticmethod
    def is_stale(
        packet: FramePacket,
        max_age_s: float,
        *,
        now_monotonic_ns: int | None = None,
    ) -> bool:
        now_ns = now_monotonic_ns or time.monotonic_ns()
        return now_ns - packet.received_monotonic_ns > int(max_age_s * 1e9)


def _default_capture_factory(source: str | int, api_preference: int | None):
    import cv2

    if api_preference is None:
        return cv2.VideoCapture(source)
    return cv2.VideoCapture(source, api_preference)


def parse_video_source(source: str | int) -> str | int:
    if isinstance(source, int):
        return source
    text = str(source).strip()
    if text.isdecimal():
        return int(text)
    return text


class VideoReceiver:
    def __init__(
        self,
        config: VideoConfig,
        *,
        capture_factory: Callable[[str | int, int | None], Any] = _default_capture_factory,
    ) -> None:
        self.config = config
        self.source = parse_video_source(config.source)
        self._capture_factory = capture_factory
        self._buffer = LatestFrameBuffer()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._capture = None
        self._capture_lock = threading.Lock()
        self._state = VideoState.STOPPED
        self._state_lock = threading.Lock()
        self._reconnect_count = 0

    @property
    def state(self) -> VideoState:
        with self._state_lock:
            return self._state

    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count

    @property
    def dropped_frames(self) -> int:
        return self._buffer.dropped_frames

    def _set_state(self, state: VideoState) -> None:
        with self._state_lock:
            if state != self._state:
                logger.info("video state %s -> %s", self._state.value, state.value)
            self._state = state

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="video-receiver",
            daemon=True,
        )
        self._thread.start()

    def read_latest(self, after_frame_id: int, timeout_s: float = 0.25) -> FramePacket | None:
        return self._buffer.get_after(after_frame_id, timeout_s)

    def is_stale(self, packet: FramePacket) -> bool:
        return self._buffer.is_stale(packet, self.config.max_frame_age_s)

    def _api_preference(self) -> int | None:
        if self.config.backend != "gstreamer":
            return None
        import cv2

        return cv2.CAP_GSTREAMER

    def _run(self) -> None:
        frame_id = 0
        first_attempt = True
        while not self._stop_event.is_set():
            self._set_state(
                VideoState.CONNECTING if first_attempt else VideoState.RECONNECTING
            )
            first_attempt = False
            capture = None
            try:
                capture = self._capture_factory(self.source, self._api_preference())
                with self._capture_lock:
                    self._capture = capture
                if not capture.isOpened():
                    raise RuntimeError(f"cannot open video source {self.source!r}")
                try:
                    import cv2

                    capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.frame_width)
                    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.frame_height)
                    capture.set(
                        cv2.CAP_PROP_BUFFERSIZE,
                        self.config.capture_buffer_size,
                    )
                except (AttributeError, ImportError):
                    pass

                self._set_state(VideoState.CONNECTED)
                consecutive_failures = 0
                while not self._stop_event.is_set():
                    ok, frame = capture.read()
                    if not ok or frame is None:
                        consecutive_failures += 1
                        if consecutive_failures >= self.config.max_consecutive_failures:
                            raise RuntimeError(
                                f"video read failed {consecutive_failures} consecutive times"
                            )
                        self._stop_event.wait(0.01)
                        continue

                    consecutive_failures = 0
                    frame_id += 1
                    height, width = frame.shape[:2]
                    self._buffer.put(
                        FramePacket(
                            frame_id=frame_id,
                            capture_timestamp_ns=time.time_ns(),
                            received_monotonic_ns=time.monotonic_ns(),
                            image_width=int(width),
                            image_height=int(height),
                            frame=frame,
                        )
                    )
            except Exception as exc:  # connection errors are retried by design
                if not self._stop_event.is_set():
                    self._reconnect_count += 1
                    logger.warning("video connection/read failure: %s", exc)
            finally:
                with self._capture_lock:
                    if self._capture is capture:
                        self._capture = None
                if capture is not None:
                    try:
                        capture.release()
                    except Exception:
                        logger.debug("video release failed", exc_info=True)
            if not self._stop_event.is_set():
                self._set_state(VideoState.RECONNECTING)
                self._stop_event.wait(self.config.reconnect_interval_s)
        self._set_state(VideoState.STOPPED)

    def close(self) -> None:
        self._stop_event.set()
        with self._capture_lock:
            capture = self._capture
        if capture is not None:
            try:
                capture.release()
            except Exception:
                logger.debug("video release during shutdown failed", exc_info=True)
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.config.reconnect_interval_s + 0.5))
        self._set_state(VideoState.STOPPED)
