"""Tests for the Pi-only operator application's safety boundary."""

import json
import socket
import subprocess
import threading
from pathlib import Path

from operator_app.gateway_client import GatewayClient
from operator_app.stack_manager import (
    RepositoryStatus,
    StackManager,
    StackStatus,
    software_update_blockers,
    stack_stop_is_safe,
    validation_stack_stop_is_safe,
)
from operator_app.validation_history import ValidationHistory


def serve_one_response(path: Path, response: dict) -> threading.Thread:
    """Serve one local gateway response for a client protocol test."""
    ready = threading.Event()

    def run() -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path))
            server.listen(1)
            ready.set()
            connection, _ = server.accept()
            with connection:
                request = connection.recv(4096)
                assert json.loads(request.decode('utf-8')) == {
                    'command': 'status'
                }
                payload = json.dumps(response).encode('utf-8') + b'\n'
                connection.sendall(payload)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert ready.wait(1.0)
    return thread


def test_gateway_client_reads_status_from_local_unix_socket(tmp_path):
    """Decode a status response without opening a network TCP port."""
    socket_path = tmp_path / 'gateway.sock'
    expected = {'mission_state': 'IDLE', 'start_allowed': False}
    thread = serve_one_response(
        socket_path,
        {'ok': True, 'status': expected},
    )
    assert GatewayClient(socket_path).status() == expected
    thread.join(timeout=1.0)
    assert not thread.is_alive()


def test_stack_stop_requires_proven_disarmed_ground_state():
    """Reject stack shutdown unless every ground-state signal is present."""
    safe = {
        'gateway_online': True,
        'mavros_connected': True,
        'armed': False,
        'landed_state': 1,
        'mission_state': 'IDLE',
    }
    assert stack_stop_is_safe(safe)
    for field, unsafe_value in (
        ('gateway_online', False),
        ('mavros_connected', False),
        ('armed', True),
        ('landed_state', 2),
        ('mission_state', 'TAKEOFF'),
    ):
        unsafe = dict(safe)
        unsafe[field] = unsafe_value
        assert not stack_stop_is_safe(unsafe)


def test_validation_stack_stop_requires_inactive_validation():
    """Do not terminate the validation controller while its FSM is active."""
    safe = {
        'gateway_online': True,
        'mavros_connected': True,
        'armed': False,
        'landed_state': 1,
        'validation_state': 'COMPLETE',
    }
    assert validation_stack_stop_is_safe(safe)
    safe['validation_state'] = 'DISTANCE_CONTROL'
    assert not validation_stack_stop_is_safe(safe)


def test_validation_history_records_terminal_result_once(tmp_path):
    """Persist one terminal result and deduplicate it by its log identity."""
    history = ValidationHistory(tmp_path / 'validation.jsonl')
    status = {
        'validation_readiness': {'profile': 'TETHERED_1M_DISTANCE'},
        'battery_percent': 82.0,
        'lidar_m': 1.0,
        'flight_mode': 'AUTO.LAND',
        'landed_state': 1,
    }
    result = 'SUCCESS log=/workspace/logs/distance_mission/test.csv'
    assert history.append_terminal(result, status, 'abc123')
    assert not history.append_terminal(result, status, 'abc123')
    records = history.load()
    assert len(records) == 1
    assert records[0]['result'] == result
    assert records[0]['revision'] == 'abc123'


def safe_update_inputs():
    """Return one fully proven software-update state."""
    status = {
        'gateway_online': True,
        'mavros_connected': True,
        'armed': False,
        'landed_state': 1,
        'mission_state': 'IDLE',
        'validation_state': 'COMPLETE',
    }
    stack = StackStatus(
        mavros_running=True,
        gateway_running=True,
        mission_running=False,
        validation_sensor_running=False,
        validation_mission_running=False,
        running_services=('operator-gateway', 'qgc-mavros'),
    )
    repository = RepositoryStatus(
        revision='111111111111',
        remote_revision='222222222222',
        branch='main',
        dirty=False,
        ahead=0,
        behind=1,
        commits=('2222222  update',),
    )
    return status, stack, repository


def test_software_update_requires_disarmed_ground_and_stopped_missions():
    """Enable update only after every live flight gate is proven safe."""
    status, stack, repository = safe_update_inputs()
    assert software_update_blockers(status, stack, repository) == []

    armed = dict(status, armed=True)
    assert '기체가 DISARM 상태여야 함' in software_update_blockers(
        armed, stack, repository
    )
    airborne = dict(status, landed_state=2)
    assert 'PX4 지상 상태 확인 필요' in software_update_blockers(
        airborne, stack, repository
    )
    active_stack = StackStatus(
        **{**stack.__dict__, 'mission_running': True}
    )
    assert any(
        '미션 스택' in blocker
        for blocker in software_update_blockers(status, active_stack, repository)
    )


def test_software_update_rejects_dirty_ahead_or_unchanged_repository():
    """Never auto-merge local field edits or unpublished commits."""
    status, stack, repository = safe_update_inputs()
    dirty = RepositoryStatus(**{**repository.__dict__, 'dirty': True})
    ahead = RepositoryStatus(**{**repository.__dict__, 'ahead': 1})
    unchanged = RepositoryStatus(**{**repository.__dict__, 'behind': 0})
    assert any('미커밋' in item for item in software_update_blockers(status, stack, dirty))
    assert any(
        'push' in item
        for item in software_update_blockers(status, stack, ahead)
    )
    assert any(
        '새 원격' in item
        for item in software_update_blockers(status, stack, unchanged)
    )


def run_git(path: Path, *arguments: str) -> str:
    """Run one isolated Git command for updater integration tests."""
    result = subprocess.run(
        ['git', *arguments],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_verified_update_fast_forwards_only_after_final_safety_check(
    tmp_path,
    monkeypatch,
):
    """Exercise the real fetch/worktree/fast-forward transaction without Docker."""
    remote = tmp_path / 'remote.git'
    seed = tmp_path / 'seed'
    checkout = tmp_path / 'checkout'
    remote.mkdir()
    run_git(remote, 'init', '--bare')
    seed.mkdir()
    run_git(seed, 'init', '-b', 'main')
    run_git(seed, 'config', 'user.name', 'Updater Test')
    run_git(seed, 'config', 'user.email', 'updater@example.invalid')
    (seed / 'value.txt').write_text('one\n', encoding='utf-8')
    run_git(seed, 'add', 'value.txt')
    run_git(seed, 'commit', '-m', 'first')
    run_git(seed, 'remote', 'add', 'origin', str(remote))
    run_git(seed, 'push', '-u', 'origin', 'main')
    run_git(tmp_path, 'clone', '--branch', 'main', str(remote), str(checkout))
    (seed / 'value.txt').write_text('two\n', encoding='utf-8')
    run_git(seed, 'commit', '-am', 'second')
    run_git(seed, 'push', 'origin', 'main')

    manager = StackManager(checkout, tmp_path / 'compose.yaml')
    monkeypatch.setattr(manager, '_verify_candidate', lambda stage: None)
    monkeypatch.setattr(manager, '_build_ros_workspace', lambda root: None)
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    repository = manager.repository_status(fetch=True)
    checks = []

    result = manager.apply_remote_update(
        repository.remote_revision,
        lambda: checks.append(True) or [],
    )

    assert checks == [True]
    assert result.commit_count == 1
    assert (checkout / 'value.txt').read_text(encoding='utf-8') == 'two\n'
