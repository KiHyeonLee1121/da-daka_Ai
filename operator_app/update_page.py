"""Fail-closed software-update page for the Raspberry Pi operator app."""

from typing import Callable, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from operator_app.stack_manager import (
    RepositoryStatus,
    StackStatus,
    software_update_blockers,
)
from operator_app.ui_components import StatusCard


class UpdatePage(QWidget):
    """Show remote commits and allow only verified ground-state updates."""

    def __init__(
        self,
        *,
        refresh_repository: Callable[[], None],
        apply_update: Callable[[], None],
        restart_app: Callable[[], None],
    ) -> None:
        super().__init__()
        self._refresh_repository = refresh_repository
        self._apply_update = apply_update
        self._restart_app = restart_app
        self._status: dict = {}
        self._stack_status: Optional[StackStatus] = None
        self._repository: Optional[RepositoryStatus] = None
        self._busy = False
        self._update_applied = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)
        title = QLabel('소프트웨어 업데이트')
        title.setObjectName('title')
        subtitle = QLabel(
            'GitHub origin/main 검증 → DISARM·지상 재확인 → fast-forward 적용'
        )
        subtitle.setObjectName('subtitle')
        root.addWidget(title)
        root.addWidget(subtitle)

        self.banner = QLabel('원격 커밋을 확인하십시오.')
        self.banner.setObjectName('bannerWarning')
        self.banner.setAlignment(Qt.AlignCenter)
        self.banner.setMinimumHeight(48)
        root.addWidget(self.banner)

        cards = QGridLayout()
        cards.setSpacing(12)
        self.flight_card = StatusCard(
            '업데이트 안전조건', ('PX4 연결', 'ARM', '착륙 상태', '미션 스택')
        )
        self.repo_card = StatusCard(
            '저장소', ('브랜치', '현재 커밋', '원격 커밋', '작업트리')
        )
        self.diff_card = StatusCard(
            '버전 차이', ('로컬 전용', '원격 신규', '적용 방식', '검증')
        )
        cards.addWidget(self.flight_card, 0, 0)
        cards.addWidget(self.repo_card, 0, 1)
        cards.addWidget(self.diff_card, 0, 2)
        root.addLayout(cards)

        content = QHBoxLayout()
        commit_frame = QFrame()
        commit_frame.setObjectName('card')
        commit_layout = QVBoxLayout(commit_frame)
        commit_title = QLabel('적용 예정 원격 커밋')
        commit_title.setObjectName('cardTitle')
        self.commits = QListWidget()
        commit_layout.addWidget(commit_title)
        commit_layout.addWidget(self.commits)
        content.addWidget(commit_frame, 3)

        blocker_frame = QFrame()
        blocker_frame.setObjectName('card')
        blocker_layout = QVBoxLayout(blocker_frame)
        blocker_title = QLabel('업데이트 차단 사유')
        blocker_title.setObjectName('cardTitle')
        self.blockers = QListWidget()
        blocker_layout.addWidget(blocker_title)
        blocker_layout.addWidget(self.blockers)
        content.addWidget(blocker_frame, 3)

        log_frame = QFrame()
        log_frame.setObjectName('card')
        log_layout = QVBoxLayout(log_frame)
        log_title = QLabel('업데이트 결과')
        log_title.setObjectName('cardTitle')
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText('조회·검증·적용 결과가 표시됩니다.')
        log_layout.addWidget(log_title)
        log_layout.addWidget(self.log)
        content.addWidget(log_frame, 4)
        root.addLayout(content, 1)

        controls = QHBoxLayout()
        self.refresh_button = QPushButton('원격 커밋 확인')
        self.refresh_button.clicked.connect(self._refresh_repository)
        self.apply_button = QPushButton('검증 후 업데이트 적용')
        self.apply_button.setObjectName('startButton')
        self.apply_button.clicked.connect(self._apply_update)
        self.restart_button = QPushButton('새 버전으로 앱 재시작')
        self.restart_button.clicked.connect(self._restart_app)
        controls.addWidget(self.refresh_button)
        controls.addStretch(1)
        controls.addWidget(self.apply_button)
        controls.addWidget(self.restart_button)
        root.addLayout(controls)

        warning = QLabel(
            '자동 merge나 강제 reset은 수행하지 않습니다. 로컬 변경 또는 미푸시 '
            '커밋이 있으면 적용이 차단됩니다. 업데이트 중에는 기체를 ARM하지 마십시오.'
        )
        warning.setWordWrap(True)
        warning.setObjectName('footer')
        root.addWidget(warning)
        self._refresh_view()

    def render_live_status(
        self,
        status: dict,
        stack_status: Optional[StackStatus],
        busy: bool,
    ) -> None:
        """Update flight and stack gates from the latest live snapshot."""
        self._status = dict(status)
        self._stack_status = stack_status
        self._busy = busy
        self._refresh_view()

    def render_disconnected(self) -> None:
        """Fail closed when the gateway cannot prove the vehicle state."""
        self._status = {}
        self._refresh_view()

    def render_repository(self, repository: RepositoryStatus) -> None:
        """Show the fetched origin/main comparison."""
        self._repository = repository
        self._busy = False
        self._update_applied = False
        self._refresh_view()

    def set_busy(self, busy: bool, message: str = '') -> None:
        """Disable update controls while a fetch or application is running."""
        self._busy = busy
        if message:
            self.log.setPlainText(message)
        self._refresh_view()

    def set_update_complete(self, message: str) -> None:
        """Expose restart only after the candidate was applied and rebuilt."""
        self._busy = False
        self._update_applied = True
        self.log.setPlainText(message)
        self._refresh_view()

    def set_error(self, message: str) -> None:
        """Show a failed fetch or update without enabling restart."""
        self._busy = False
        self._update_applied = False
        self.log.setPlainText(message)
        self._refresh_view()

    def blockers_now(self) -> list[str]:
        """Return the same gates used to enable the apply button."""
        return software_update_blockers(
            self._status,
            self._stack_status,
            self._repository,
        )

    @property
    def repository(self) -> Optional[RepositoryStatus]:
        return self._repository

    def _refresh_view(self) -> None:
        connected = bool(self._status.get('mavros_connected'))
        armed = self._status.get('armed')
        landed = self._status.get('landed_state')
        self.flight_card.set_value('PX4 연결', '정상' if connected else '확인 불가')
        self.flight_card.set_value(
            'ARM',
            'DISARMED' if armed is False and connected else '확인 불가/ARMED',
        )
        self.flight_card.set_value(
            '착륙 상태', '지상' if landed == 1 else '확인 필요'
        )
        stacks_stopped = bool(
            self._stack_status is not None
            and not self._stack_status.mission_running
            and not self._stack_status.validation_mission_running
            and not self._stack_status.validation_sensor_running
        )
        self.flight_card.set_value(
            '미션 스택', '정지됨' if stacks_stopped else '정지 필요'
        )

        repository = self._repository
        if repository is None:
            for key in ('브랜치', '현재 커밋', '원격 커밋', '작업트리'):
                self.repo_card.set_value(key, '—')
            self.diff_card.set_value('로컬 전용', '—')
            self.diff_card.set_value('원격 신규', '—')
            self.commits.clear()
            self.commits.addItem('원격 커밋 확인을 실행하십시오.')
        else:
            self.repo_card.set_value('브랜치', repository.branch)
            self.repo_card.set_value('현재 커밋', repository.revision)
            self.repo_card.set_value('원격 커밋', repository.remote_revision)
            self.repo_card.set_value(
                '작업트리', '변경 있음' if repository.dirty else '깨끗함'
            )
            self.diff_card.set_value('로컬 전용', str(repository.ahead))
            self.diff_card.set_value('원격 신규', str(repository.behind))
            self.commits.clear()
            self.commits.addItems(list(repository.commits) or ['새 원격 커밋 없음'])
        self.diff_card.set_value('적용 방식', 'fast-forward only')
        self.diff_card.set_value('검증', '격리 테스트 + ROS 빌드')

        blockers = self.blockers_now()
        self.blockers.clear()
        self.blockers.addItems(blockers or ['모든 업데이트 조건 충족'])
        self.refresh_button.setEnabled(not self._busy)
        self.apply_button.setEnabled(not blockers and not self._busy)
        self.restart_button.setEnabled(self._update_applied and not self._busy)
        if self._busy:
            self._set_banner('업데이트 작업 진행 중 · 기체를 ARM하지 마십시오', 'bannerActive')
        elif self._update_applied:
            self._set_banner('업데이트 적용 완료 · 앱 재시작 필요', 'bannerReady')
        elif not blockers:
            self._set_banner('업데이트 적용 가능 · 커밋 목록을 확인하십시오', 'bannerReady')
        else:
            self._set_banner('업데이트 적용 잠김 · 차단 사유 확인', 'bannerWarning')

    def _set_banner(self, text: str, object_name: str) -> None:
        self.banner.setText(text)
        self.banner.setObjectName(object_name)
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)
