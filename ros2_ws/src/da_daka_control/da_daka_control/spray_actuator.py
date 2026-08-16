"""Fail-closed valve backends and bounded spray pulse logic."""

from dataclasses import dataclass
import threading
import time
from typing import Optional


class ValveBackend:
    """Abstract binary valve output."""

    name = 'base'

    def set_active(self, active: bool) -> None:
        """Set the physical or simulated valve output state."""
        raise NotImplementedError

    def close(self) -> None:
        """Release resources after forcing the valve inactive."""


class MockValveBackend(ValveBackend):
    """Memory-only backend for tests and dry runs."""

    name = 'mock'

    def __init__(self) -> None:
        self.active = False
        self.transitions: list[bool] = []

    def set_active(self, active: bool) -> None:
        """Record a simulated valve transition."""
        self.active = bool(active)
        self.transitions.append(self.active)

    def close(self) -> None:
        """Force the simulated valve inactive."""
        self.set_active(False)


class GpioValveBackend(ValveBackend):
    """Drive a Linux GPIO character-device line using libgpiod."""

    name = 'gpio'

    def __init__(
        self,
        chip_path: str,
        line_offset: int,
        active_high: bool = True,
        consumer: str = 'da_daka_spray',
    ) -> None:
        if not chip_path:
            raise ValueError('gpio_chip must be configured')
        if line_offset < 0:
            raise ValueError('gpio_line_offset must be non-negative')
        try:
            import gpiod
        except ImportError as exc:
            raise RuntimeError('Python libgpiod is required') from exc

        self._active_high = bool(active_high)
        self._request = None
        self._chip = None
        self._line = None
        self._v2 = hasattr(gpiod, 'request_lines')
        if self._v2:
            from gpiod.line import Direction, Value

            self._value_active = (
                Value.ACTIVE if self._active_high else Value.INACTIVE
            )
            self._value_inactive = (
                Value.INACTIVE if self._active_high else Value.ACTIVE
            )
            settings = gpiod.LineSettings(
                direction=Direction.OUTPUT,
                output_value=self._value_inactive,
            )
            self._request = gpiod.request_lines(
                chip_path,
                consumer=consumer,
                config={int(line_offset): settings},
            )
            self._line_offset = int(line_offset)
        else:
            self._chip = gpiod.Chip(chip_path)
            self._line = self._chip.get_line(int(line_offset))
            inactive = 0 if self._active_high else 1
            self._line.request(
                consumer=consumer,
                type=gpiod.LINE_REQ_DIR_OUT,
                default_vals=[inactive],
            )

    def set_active(self, active: bool) -> None:
        """Drive the requested GPIO level."""
        if self._v2:
            value = self._value_active if active else self._value_inactive
            self._request.set_value(self._line_offset, value)
        else:
            value = int(bool(active)) if self._active_high else int(not active)
            self._line.set_value(value)

    def close(self) -> None:
        """Force the GPIO inactive and release its line request."""
        try:
            self.set_active(False)
        finally:
            if self._request is not None:
                self._request.release()
                self._request = None
            if self._line is not None:
                self._line.release()
                self._line = None
            if self._chip is not None:
                close = getattr(self._chip, 'close', None)
                if callable(close):
                    close()
                self._chip = None


@dataclass(frozen=True)
class SprayResult:
    """Result of one spray gate or pulse request."""

    success: bool
    message: str


@dataclass(frozen=True)
class SprayStatus:
    """Immutable snapshot of spray gates and pulse counters."""

    output_enabled: bool
    session_enabled: bool
    active: bool
    pulse_count: int
    maximum_pulses: int
    backend: str


class TimedSprayController:
    """Open a valve only for bounded pulses behind two explicit gates."""

    def __init__(
        self,
        backend: ValveBackend,
        *,
        output_enabled: bool,
        pulse_duration_s: float,
        minimum_pulse_s: float,
        maximum_pulse_s: float,
        cooldown_s: float,
        maximum_pulses: int,
    ) -> None:
        if minimum_pulse_s <= 0.0:
            raise ValueError('minimum_pulse_s must be positive')
        if maximum_pulse_s < minimum_pulse_s:
            raise ValueError('maximum_pulse_s must not be smaller than minimum')
        if not minimum_pulse_s <= pulse_duration_s <= maximum_pulse_s:
            raise ValueError('pulse_duration_s is outside configured bounds')
        if cooldown_s < 0.0 or maximum_pulses <= 0:
            raise ValueError('spray cooldown/count configuration is invalid')
        self.backend = backend
        self.output_enabled = bool(output_enabled)
        self.pulse_duration_s = float(pulse_duration_s)
        self.cooldown_s = float(cooldown_s)
        self.maximum_pulses = int(maximum_pulses)
        self._session_enabled = False
        self._active = False
        self._pulse_count = 0
        self._last_pulse_started: Optional[float] = None
        self._off_timer: Optional[threading.Timer] = None
        self._lock = threading.RLock()
        self.backend.set_active(False)

    def set_enabled(self, enabled: bool) -> SprayResult:
        """Open or close the per-mission spray session gate."""
        with self._lock:
            if not enabled:
                self._session_enabled = False
                self._force_off()
                return SprayResult(True, 'spray session disabled; valve closed')
            if not self.output_enabled:
                return SprayResult(False, 'output_enabled=false blocks live spray')
            if not self._session_enabled:
                self._pulse_count = 0
                self._last_pulse_started = None
            self._session_enabled = True
            return SprayResult(True, 'spray session enabled')

    def trigger(self, now_s: Optional[float] = None) -> SprayResult:
        """Start one bounded pulse if all gates and limits permit it."""
        with self._lock:
            now_s = time.monotonic() if now_s is None else float(now_s)
            if not self.output_enabled:
                return SprayResult(False, 'live spray output is disabled')
            if not self._session_enabled:
                return SprayResult(False, 'spray session is not enabled')
            if self._active:
                return SprayResult(False, 'spray pulse is already active')
            if self._pulse_count >= self.maximum_pulses:
                return SprayResult(False, 'maximum spray pulse count reached')
            if self._last_pulse_started is not None:
                elapsed_s = now_s - self._last_pulse_started
                if elapsed_s < self.cooldown_s:
                    return SprayResult(False, 'spray cooldown is active')
            self.backend.set_active(True)
            self._active = True
            self._pulse_count += 1
            self._last_pulse_started = now_s
            self._schedule_close()
            return SprayResult(
                True,
                f'spray pulse started for {self.pulse_duration_s:.3f}s',
            )

    def stop(self) -> SprayResult:
        """Force the valve closed synchronously."""
        with self._lock:
            self._force_off()
            return SprayResult(True, 'valve closed')

    def status(self) -> SprayStatus:
        """Return the current output, session and pulse state."""
        with self._lock:
            return SprayStatus(
                self.output_enabled,
                self._session_enabled,
                self._active,
                self._pulse_count,
                self.maximum_pulses,
                self.backend.name,
            )

    def close(self) -> None:
        """Disable spraying, close the valve and release the backend."""
        with self._lock:
            self._session_enabled = False
            self._force_off()
            self.backend.close()

    def _schedule_close(self) -> None:
        if self._off_timer is not None:
            self._off_timer.cancel()
        self._off_timer = threading.Timer(
            self.pulse_duration_s,
            self._automatic_close,
        )
        self._off_timer.daemon = True
        self._off_timer.start()

    def _automatic_close(self) -> None:
        with self._lock:
            self._force_off(cancel_timer=False)

    def _force_off(self, cancel_timer: bool = True) -> None:
        if cancel_timer and self._off_timer is not None:
            self._off_timer.cancel()
        self._off_timer = None
        self.backend.set_active(False)
        self._active = False
