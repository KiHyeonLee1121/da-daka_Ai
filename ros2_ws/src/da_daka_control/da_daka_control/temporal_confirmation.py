"""Fresh-sequence temporal confirmation for conservative clean decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from da_daka_control.spray_sequence import (
    perception_is_newer,
    PerceptionBarrier,
)


@dataclass(frozen=True)
class PerceptionIdentity:
    """Monotonic identity of one accepted inference result."""

    session_id: str
    sequence: int
    frame_id: int


class TemporalCleanlinessConfirmation:
    """Count only distinct fresh inference results, never timer repetitions."""

    def __init__(
        self,
        *,
        clean_consecutive_frames: int,
        dirty_consecutive_frames: int,
    ) -> None:
        if min(clean_consecutive_frames, dirty_consecutive_frames) <= 0:
            raise ValueError('temporal confirmation frame counts must be positive')
        self.clean_required = int(clean_consecutive_frames)
        self.dirty_required = int(dirty_consecutive_frames)
        self.reset()

    def reset(self) -> None:
        """Forget observations at panel/state boundaries."""
        self._last: Optional[PerceptionIdentity] = None
        self._clean_count = 0
        self._dirty_count = 0

    def observe(
        self,
        *,
        session_id: str,
        sequence: int,
        frame_id: int,
        dirt_found: bool,
        barrier: Optional[PerceptionBarrier] = None,
    ) -> Optional[bool]:
        """Return True for confirmed dirty, False for confirmed clean, else None."""
        identity = PerceptionIdentity(
            str(session_id),
            int(sequence),
            int(frame_id),
        )
        if not perception_is_newer(
            session_id=identity.session_id,
            sequence=identity.sequence,
            frame_id=identity.frame_id,
            barrier=barrier,
        ):
            return None
        if identity == self._last:
            return None
        if self._last is not None and identity.session_id == self._last.session_id:
            if (
                identity.sequence <= self._last.sequence
                or identity.frame_id <= self._last.frame_id
            ):
                raise ValueError('temporal confirmation received stale inference')
        elif self._last is not None:
            self._clean_count = 0
            self._dirty_count = 0
        self._last = identity
        if dirt_found:
            self._dirty_count += 1
            self._clean_count = 0
            return True if self._dirty_count >= self.dirty_required else None
        self._clean_count += 1
        self._dirty_count = 0
        return False if self._clean_count >= self.clean_required else None
