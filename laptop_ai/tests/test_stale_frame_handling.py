import numpy as np

from laptop_ai.video_receiver import FramePacket, LatestFrameBuffer


def packet(frame_id: int, received_ns: int) -> FramePacket:
    return FramePacket(
        frame_id=frame_id,
        capture_timestamp_ns=received_ns,
        received_monotonic_ns=received_ns,
        image_width=2,
        image_height=2,
        frame=np.zeros((2, 2, 3), dtype=np.uint8),
    )


def test_latest_frame_overwrites_unconsumed_old_frame() -> None:
    buffer = LatestFrameBuffer()
    buffer.put(packet(1, 100))
    buffer.put(packet(2, 200))
    latest = buffer.get_after(0, timeout_s=0.01)
    assert latest is not None
    assert latest.frame_id == 2
    assert buffer.dropped_frames == 1


def test_stale_frame_is_detected_from_monotonic_receive_time() -> None:
    old = packet(1, 1_000_000_000)
    assert LatestFrameBuffer.is_stale(
        old,
        max_age_s=0.4,
        now_monotonic_ns=1_500_000_001,
    )
