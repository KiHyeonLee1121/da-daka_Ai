import importlib.util
from pathlib import Path


TOOL = Path(__file__).resolve().parents[2] / 'tools/find_raspberry_pi.py'
SPEC = importlib.util.spec_from_file_location('find_raspberry_pi', TOOL)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_raspberry_pi_oui_is_likely():
    status, reason = MODULE.classify('B8:27:EB:01:02:03', '', False)
    assert status == 'RASPBERRY_PI_LIKELY'
    assert 'MAC' in reason


def test_ssh_only_is_possible_not_certain():
    status, reason = MODULE.classify('AA:BB:CC:01:02:03', '', True)
    assert status == 'POSSIBLE_PI'
    assert 'SSH' in reason


def test_pi_hostname_is_likely():
    status, _reason = MODULE.classify('', 'raspberrypi.local', False)
    assert status == 'RASPBERRY_PI_LIKELY'
