"""Tests for bounded and explicitly enabled spray pulses."""

import time

from da_daka_control.spray_actuator import (
    MockValveBackend,
    TimedSprayController,
)


def make_controller(**updates):
    backend = MockValveBackend()
    values = {
        'output_enabled': True,
        'pulse_duration_s': 0.02,
        'minimum_pulse_s': 0.01,
        'maximum_pulse_s': 0.10,
        'cooldown_s': 0.0,
        'maximum_pulses': 2,
    }
    values.update(updates)
    return backend, TimedSprayController(backend, **values)


def test_spray_requires_session_enable():
    backend, controller = make_controller()
    assert not controller.trigger().success
    assert not backend.active
    controller.close()


def test_output_gate_cannot_be_bypassed():
    backend, controller = make_controller(output_enabled=False)
    assert not controller.set_enabled(True).success
    assert not controller.trigger().success
    assert not backend.active
    controller.close()


def test_pulse_closes_automatically():
    backend, controller = make_controller()
    assert controller.set_enabled(True).success
    assert controller.trigger().success
    assert backend.active
    time.sleep(0.05)
    assert not backend.active
    controller.close()


def test_session_pulse_limit_is_enforced():
    backend, controller = make_controller(maximum_pulses=1)
    assert controller.set_enabled(True).success
    assert controller.trigger().success
    time.sleep(0.04)
    assert not controller.trigger().success
    assert not backend.active
    controller.close()
