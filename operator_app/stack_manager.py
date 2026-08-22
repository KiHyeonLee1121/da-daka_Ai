"""Manage the inert ROS stack and apply verified fast-forward updates."""

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class StackCommandError(RuntimeError):
    """Report a failed Docker Compose or Git command."""


@dataclass(frozen=True)
class StackStatus:
    """Describe which expected Compose services are running."""

    mavros_running: bool
    gateway_running: bool
    mission_running: bool
    validation_sensor_running: bool
    validation_mission_running: bool
    running_services: tuple[str, ...]


@dataclass(frozen=True)
class RepositoryStatus:
    """Describe the local checkout relative to origin/main."""

    revision: str
    remote_revision: str
    branch: str
    dirty: bool
    ahead: int
    behind: int
    commits: tuple[str, ...]


@dataclass(frozen=True)
class UpdateResult:
    """Describe one successfully verified and applied repository update."""

    previous_revision: str
    revision: str
    commit_count: int


UPDATE_INACTIVE_STATES = {'IDLE', 'COMPLETE', 'ABORT'}


def repository_update_blockers(repository: RepositoryStatus | None) -> list[str]:
    """Return repository-only reasons that prevent a fast-forward update."""
    if repository is None:
        return ['원격 저장소 상태 확인 필요']
    blockers = []
    if repository.branch != 'main':
        blockers.append('main 브랜치에서만 업데이트 가능')
    if repository.dirty:
        blockers.append('로컬 미커밋 변경사항을 먼저 보존해야 함')
    if repository.ahead:
        blockers.append('원격에 없는 로컬 커밋을 먼저 push해야 함')
    if repository.behind <= 0:
        blockers.append('적용할 새 원격 커밋 없음')
    return blockers


def software_update_blockers(
    status: dict,
    stack_status: StackStatus | None,
    repository: RepositoryStatus | None,
) -> list[str]:
    """Return every reason a live software update must remain disabled."""
    blockers = []
    if not status.get('gateway_online'):
        blockers.append('ROS 운영 gateway 연결 필요')
    if not status.get('mavros_connected'):
        blockers.append('PX4/MAVROS 연결 필요')
    if status.get('armed') is not False:
        blockers.append('기체가 DISARM 상태여야 함')
    if status.get('landed_state') != 1:
        blockers.append('PX4 지상 상태 확인 필요')
    mission_state = str(status.get('mission_state', 'UNKNOWN'))
    if mission_state not in {'UNKNOWN', *UPDATE_INACTIVE_STATES}:
        blockers.append(f'자율 청소 미션 진행 중 ({mission_state})')
    validation_state = str(status.get('validation_state', 'UNKNOWN'))
    if validation_state not in {'UNKNOWN', *UPDATE_INACTIVE_STATES}:
        blockers.append(f'실기체 검증 진행 중 ({validation_state})')
    if stack_status is None:
        blockers.append('ROS 스택 상태 확인 필요')
    else:
        if stack_status.mission_running:
            blockers.append('자율 청소 미션 스택을 먼저 정지해야 함')
        if stack_status.validation_mission_running:
            blockers.append('실기체 검증 스택을 먼저 정지해야 함')
        if stack_status.validation_sensor_running:
            blockers.append('실기체 검증 센서 스택을 먼저 정지해야 함')
    blockers.extend(repository_update_blockers(repository))
    return blockers


class StackManager:
    """Run only fixed, reviewable host-side maintenance commands."""

    def __init__(self, project_root: Path, compose_file: Path) -> None:
        """Store the canonical project and Compose locations."""
        self.project_root = Path(project_root)
        self.compose_file = Path(compose_file)
        self.compose_root = self.compose_file.parent

    def _run(
        self,
        command: list[str],
        *,
        cwd: Path,
        timeout_s: float = 30.0,
    ) -> str:
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StackCommandError(str(exc)) from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise StackCommandError(detail or f'command failed: {command[0]}')
        return completed.stdout.strip()

    def stack_status(self) -> StackStatus:
        """Inspect running services without changing container state."""
        output = self._run(
            [
                'docker',
                'compose',
                '-f',
                str(self.compose_file),
                '--profile',
                'autonomous-cleaning',
                '--profile',
                'distance-test',
                'ps',
                '--status',
                'running',
                '--services',
            ],
            cwd=self.compose_root,
            timeout_s=10.0,
        )
        services = tuple(sorted(line for line in output.splitlines() if line))
        return StackStatus(
            mavros_running='qgc-mavros' in services,
            gateway_running='operator-gateway' in services,
            mission_running='autonomous-cleaning' in services,
            validation_sensor_running='distance-sensor' in services,
            validation_mission_running='distance-mission' in services,
            running_services=services,
        )

    def start_stack(self) -> str:
        """Start the locked autonomous stack; this never starts a mission."""
        if self.stack_status().validation_mission_running:
            raise StackCommandError(
                'flight validation stack is running; stop it first'
            )
        runtime_dir = self.project_root / 'ros2_ws' / 'run'
        runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        return self._run(
            [
                'docker',
                'compose',
                '-f',
                str(self.compose_file),
                '--profile',
                'autonomous-cleaning',
                'up',
                '-d',
                'qgc-mavros',
                'operator-gateway',
                'autonomous-cleaning',
            ],
            cwd=self.compose_root,
            timeout_s=60.0,
        )

    def stop_mission_stack(self) -> str:
        """Stop only the mission container, leaving MAVROS/QGC available."""
        return self._run(
            [
                'docker',
                'compose',
                '-f',
                str(self.compose_file),
                '--profile',
                'autonomous-cleaning',
                'stop',
                'autonomous-cleaning',
            ],
            cwd=self.compose_root,
            timeout_s=30.0,
        )

    def start_validation_stack(self) -> str:
        """Start the locked 1 m validation profile without starting flight."""
        if self.stack_status().mission_running:
            raise StackCommandError(
                'autonomous cleaning stack is running; stop it first'
            )
        runtime_dir = self.project_root / 'ros2_ws' / 'run'
        runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        return self._run(
            [
                'docker',
                'compose',
                '-f',
                str(self.compose_file),
                '--profile',
                'distance-test',
                'up',
                '-d',
                'qgc-mavros',
                'operator-gateway',
                'distance-sensor',
                'distance-mission',
            ],
            cwd=self.compose_root,
            timeout_s=60.0,
        )

    def stop_validation_stack(self) -> str:
        """Stop validation nodes while preserving the QGC/MAVROS link."""
        return self._run(
            [
                'docker',
                'compose',
                '-f',
                str(self.compose_file),
                '--profile',
                'distance-test',
                'stop',
                'distance-mission',
                'distance-sensor',
            ],
            cwd=self.compose_root,
            timeout_s=30.0,
        )

    def repository_status(self, *, fetch: bool = False) -> RepositoryStatus:
        """Compare the current checkout to origin/main without applying it."""
        if fetch:
            self._run(
                ['git', 'fetch', '--prune', 'origin'],
                cwd=self.project_root,
                timeout_s=30.0,
            )
        revision = self._run(
            ['git', 'rev-parse', '--short=12', 'HEAD'],
            cwd=self.project_root,
        )
        remote_revision = self._run(
            ['git', 'rev-parse', '--short=12', 'origin/main'],
            cwd=self.project_root,
        )
        branch = self._run(
            ['git', 'branch', '--show-current'],
            cwd=self.project_root,
        )
        dirty = bool(
            self._run(
                ['git', 'status', '--porcelain'],
                cwd=self.project_root,
            )
        )
        counts = self._run(
            [
                'git',
                'rev-list',
                '--left-right',
                '--count',
                'HEAD...origin/main',
            ],
            cwd=self.project_root,
        ).split()
        if len(counts) != 2:
            raise StackCommandError('could not compare HEAD with origin/main')
        commit_output = self._run(
            [
                'git',
                'log',
                '--format=%h  %s',
                '--max-count=50',
                'HEAD..origin/main',
            ],
            cwd=self.project_root,
        )
        return RepositoryStatus(
            revision=revision,
            remote_revision=remote_revision,
            branch=branch or '(detached)',
            dirty=dirty,
            ahead=int(counts[0]),
            behind=int(counts[1]),
            commits=tuple(line for line in commit_output.splitlines() if line),
        )

    def apply_remote_update(
        self,
        expected_remote_revision: str,
        safety_check: Callable[[], list[str]],
    ) -> UpdateResult:
        """Verify origin/main in isolation, recheck safety, and fast-forward."""
        repository = self.repository_status(fetch=True)
        if repository.remote_revision != expected_remote_revision:
            raise StackCommandError(
                '원격 커밋이 확인 이후 변경되었습니다. 다시 확인하십시오.'
            )
        repository_blockers = repository_update_blockers(repository)
        if repository_blockers:
            raise StackCommandError('; '.join(repository_blockers))

        stage_parent = (
            Path.home() / '.local' / 'share' / 'da-daka' / 'update-staging'
        )
        stage_parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='candidate-', dir=stage_parent))
        worktree_added = False
        try:
            self._run(
                [
                    'git',
                    'worktree',
                    'add',
                    '--detach',
                    str(stage),
                    'origin/main',
                ],
                cwd=self.project_root,
                timeout_s=60.0,
            )
            worktree_added = True
            self._verify_candidate(stage)

            blockers = safety_check()
            if blockers:
                raise StackCommandError(
                    '최종 안전 확인 실패: ' + '; '.join(blockers)
                )
            current = self.repository_status(fetch=False)
            if current.revision != repository.revision:
                raise StackCommandError('검증 중 로컬 HEAD가 변경되었습니다.')
            if current.remote_revision != repository.remote_revision:
                raise StackCommandError('검증 중 원격 기준 커밋이 변경되었습니다.')
            if current.dirty:
                raise StackCommandError('검증 중 로컬 작업트리가 변경되었습니다.')

            self._run(
                ['git', 'merge', '--ff-only', 'origin/main'],
                cwd=self.project_root,
                timeout_s=60.0,
            )
            self._build_ros_workspace(self.project_root)
            applied = self.repository_status(fetch=False)
            return UpdateResult(
                previous_revision=repository.revision,
                revision=applied.revision,
                commit_count=repository.behind,
            )
        finally:
            if worktree_added:
                try:
                    self._run(
                        ['git', 'worktree', 'remove', '--force', str(stage)],
                        cwd=self.project_root,
                        timeout_s=60.0,
                    )
                except StackCommandError:
                    pass
            else:
                try:
                    stage.rmdir()
                except OSError:
                    pass

    def _verify_candidate(self, stage: Path) -> None:
        """Run host tests and an isolated ROS build before touching HEAD."""
        self._run(
            [
                'python3',
                '-m',
                'compileall',
                '-q',
                'operator_app',
                'laptop_ai/laptop_ai',
                'ros2_ws/src/da_daka_control/da_daka_control',
                'ros2_ws/src/da_daka_control/launch',
            ],
            cwd=stage,
            timeout_s=120.0,
        )
        self._run(
            ['python3', '-m', 'pytest', '-q', 'tests'],
            cwd=stage,
            timeout_s=300.0,
        )
        self._run(
            ['python3', '-m', 'pytest', '-q', 'tests'],
            cwd=stage / 'laptop_ai',
            timeout_s=300.0,
        )
        self._build_ros_workspace(stage)

    def _build_ros_workspace(self, root: Path) -> None:
        """Build one repository workspace without requiring flight devices."""
        workspace = root / 'ros2_ws'
        self._run(
            [
                'docker',
                'run',
                '--rm',
                '-v',
                f'{workspace}:/workspace',
                '-w',
                '/workspace',
                'local/ros2-jazzy-mavros:latest',
                'bash',
                '-lc',
                'source /opt/ros/jazzy/setup.bash && '
                'colcon build --symlink-install',
            ],
            cwd=root,
            timeout_s=900.0,
        )


def stack_stop_is_safe(status: dict) -> bool:
    """Permit stopping mission processes only when ground state is proven."""
    return bool(
        status.get('gateway_online')
        and status.get('mavros_connected')
        and not status.get('armed')
        and status.get('landed_state') == 1
        and status.get('mission_state') in {'IDLE', 'COMPLETE', 'ABORT'}
    )


def validation_stack_stop_is_safe(status: dict) -> bool:
    """Permit validation shutdown only after a proven safe ground state."""
    return bool(
        status.get('gateway_online')
        and status.get('mavros_connected')
        and not status.get('armed')
        and status.get('landed_state') == 1
        and status.get('validation_state') in {
            'IDLE',
            'COMPLETE',
            'ABORT',
        }
    )
