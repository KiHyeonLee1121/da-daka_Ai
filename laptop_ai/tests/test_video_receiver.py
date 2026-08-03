import time

import numpy as np

from laptop_ai.config import VideoConfig
from laptop_ai.video_receiver import VideoReceiver


class FakeCapture:
    def __init__(self, opened: bool, frames=None) -> None:
        self.opened = opened
        self.frames = list(frames or [])
        self.released = False

    def isOpened(self) -> bool:
        return self.opened

    def set(self, *_args) -> None:
        pass

    def read(self):
        if self.frames:
            return True, self.frames.pop(0)
        return False, None

    def release(self) -> None:
        self.released = True


def test_failed_connection_transitions_to_reconnect_and_recovers() -> None:
    image = np.zeros((4, 6, 3), dtype=np.uint8)
    captures = [FakeCapture(False), FakeCapture(True, [image])]

    def factory(_source, _api):
        if captures:
            return captures.pop(0)
        return FakeCapture(False)

    receiver = VideoReceiver(
        VideoConfig(
            source=0,
            reconnect_interval_s=0.01,
            max_consecutive_failures=1,
            max_frame_age_s=1.0,
        ),
        capture_factory=factory,
    )
    receiver.start()
    deadline = time.monotonic() + 1.0
    recovered = None
    while time.monotonic() < deadline and recovered is None:
        recovered = receiver.read_latest(0, timeout_s=0.02)
    receiver.close()
    assert recovered is not None
    assert recovered.image_width == 6
    assert receiver.reconnect_count >= 1
