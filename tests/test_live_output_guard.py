"""Tests for the explicit legacy live-output safety guard."""

import pytest

from main import validate_legacy_live_output


def test_dry_run_is_allowed_without_override():
    config = {
        "mavlink": {"dry_run": True},
        "spray": {"dry_run": True},
    }

    validate_legacy_live_output(config, explicitly_allowed=False)


@pytest.mark.parametrize(
    "config",
    [
        {"mavlink": {"dry_run": False}, "spray": {"dry_run": True}},
        {"mavlink": {"dry_run": True}, "spray": {"dry_run": False}},
    ],
)
def test_live_output_requires_explicit_override(config):
    with pytest.raises(RuntimeError, match="Legacy live output is blocked"):
        validate_legacy_live_output(config, explicitly_allowed=False)


def test_explicit_override_allows_approved_bench_test():
    config = {
        "mavlink": {"dry_run": False},
        "spray": {"dry_run": False},
    }

    validate_legacy_live_output(config, explicitly_allowed=True)
