"""Qt main window for local VNC operation of the DA-DAKA drone."""

import subprocess
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QColor, QFont, QPalette, QTextCursor
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from operator_app import __version__
from operator_app.gateway_client import GatewayClient, GatewayError
from operator_app.stack_manager import (
    RepositoryStatus,
    StackManager,
    StackStatus,
    UpdateResult,
    software_update_blockers,
    stack_stop_is_safe,
    validation_stack_stop_is_safe,
)
from operator_app.ui_components import StatusCard, display_value, translate_failure
from operator_app.update_page import UpdatePage
from operator_app.validation_page import ValidationPage


INACTIVE_STATES = {'IDLE', 'COMPLETE', 'ABORT'}


class OperatorWindow(QMainWindow):
    """Display status and issue only high-level mission commands."""

    def __init__(
        self,
        project_root: Path,
        gateway: GatewayClient,
        stack: StackManager,
    ) -> None:
        """Build the operator window around local gateway dependencies."""
        super().__init__()
        self.project_root = project_root
        self.gateway = gateway
        self.stack = stack
        self.executor = ThreadPoolExecutor(max_workers=3)
        self._status_future: Future | None = None
        self._stack_future: Future | None = None
        self._command_future: Future | None = None
        self._repository_future: Future | None = None
        self._update_future: Future | None = None
        self._status: dict = {}
        self._stack_status: StackStatus | None = None
        self._last_gateway_ok_s: float | None = None
        self._last_mission_result = ''
        self._build_ui()
        self._apply_style()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._poll)
        self.refresh_timer.start(500)
        self._poll()
        self._check_repository(fetch=False)

    def _build_ui(self) -> None:
        self.setWindowTitle('DA-DAKA 드론 운영 콘솔')
        self.setMinimumSize(1080, 720)
        central = QWidget()
        self.setCentralWidget(central)
        shell = QVBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        shell.addWidget(self.tabs)
        operation_page = QWidget()
        self.tabs.addTab(operation_page, '자율 청소 운영')
        root = QVBoxLayout(operation_page)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel('DA-DAKA 운영 콘솔')
        title.setObjectName('title')
        subtitle = QLabel('Raspberry Pi 5 · ROS 2 자율 청소 미션')
        subtitle.setObjectName('subtitle')
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding))
        self.version_label = QLabel(f'앱 {__version__}')
        self.version_label.setObjectName('version')
        header.addWidget(self.version_label)
        root.addLayout(header)

        self.banner = QLabel('ROS 운영 게이트웨이 연결 대기 중')
        self.banner.setObjectName('bannerWarning')
        self.banner.setAlignment(Qt.AlignCenter)
        self.banner.setMinimumHeight(48)
        root.addWidget(self.banner)

        cards = QGridLayout()
        cards.setSpacing(12)
        self.flight_card = StatusCard(
            '비행 제어', ('PX4 연결', 'ARM', '비행 모드', '착륙 상태')
        )
        self.mission_card = StatusCard(
            '미션', ('상태', '현재 패널', '시작 서비스', '시작 잠금')
        )
        self.sensor_card = StatusCard(
            '센서·AI', ('배터리', 'LiDAR', '노트북 AI', '고도 가드')
        )
        self.spray_card = StatusCard(
            '분사장치', ('백엔드', '물리 출력', '미션 세션', '실제 분사 요구')
        )
        cards.addWidget(self.flight_card, 0, 0)
        cards.addWidget(self.mission_card, 0, 1)
        cards.addWidget(self.sensor_card, 0, 2)
        cards.addWidget(self.spray_card, 0, 3)
        root.addLayout(cards)

        middle = QHBoxLayout()
        blocker_frame = QFrame()
        blocker_frame.setObjectName('card')
        blocker_layout = QVBoxLayout(blocker_frame)
        blocker_title = QLabel('시작 차단 사유')
        blocker_title.setObjectName('cardTitle')
        self.blockers = QListWidget()
        self.blockers.setAlternatingRowColors(True)
        blocker_layout.addWidget(blocker_title)
        blocker_layout.addWidget(self.blockers)
        middle.addWidget(blocker_frame, 3)

        result_frame = QFrame()
        result_frame.setObjectName('card')
        result_layout = QVBoxLayout(result_frame)
        result_title = QLabel('최근 결과·운영 메시지')
        result_title.setObjectName('cardTitle')
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setPlaceholderText('미션 결과와 앱 메시지가 표시됩니다.')
        result_layout.addWidget(result_title)
        result_layout.addWidget(self.result_text)
        middle.addWidget(result_frame, 2)
        root.addLayout(middle, 1)

        controls = QHBoxLayout()
        self.stack_start_button = QPushButton('ROS 스택 시작')
        self.stack_start_button.clicked.connect(self._start_stack)
        self.stack_stop_button = QPushButton('미션 스택 정지')
        self.stack_stop_button.clicked.connect(self._stop_stack)
        self.update_button = QPushButton('소프트웨어 업데이트')
        self.update_button.clicked.connect(self._show_update_page)
        self.start_button = QPushButton('자율 청소 시작')
        self.start_button.setObjectName('startButton')
        self.start_button.clicked.connect(self._request_start)
        self.abort_button = QPushButton('미션 중단·착륙 요청')
        self.abort_button.setObjectName('abortButton')
        self.abort_button.clicked.connect(self._request_abort)
        controls.addWidget(self.stack_start_button)
        controls.addWidget(self.stack_stop_button)
        controls.addWidget(self.update_button)
        controls.addStretch(1)
        controls.addWidget(self.start_button)
        controls.addWidget(self.abort_button)
        root.addLayout(controls)

        self.footer = QLabel('로컬 저장소 상태 확인 중')
        self.footer.setObjectName('footer')
        root.addWidget(self.footer)

        history_path = (
            Path.home()
            / '.local'
            / 'share'
            / 'da-daka'
            / 'validation_history.jsonl'
        )
        self.validation_page = ValidationPage(
            history_path,
            start_stack=self._start_validation_stack,
            stop_stack=self._stop_validation_stack,
            start_validation=self._request_validation_start,
            abort_validation=self._request_validation_abort,
        )
        self.tabs.addTab(self.validation_page, '실기체 비행 검증')
        self.update_page = UpdatePage(
            refresh_repository=lambda: self._check_repository(fetch=True),
            apply_update=self._request_update,
            restart_app=self._restart_app,
        )
        self.tabs.addTab(self.update_page, '소프트웨어 업데이트')

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #111827; color: #e5e7eb; }
            QTabWidget::pane { border: 1px solid #334155; }
            QTabBar::tab { background: #1f2937; color: #94a3b8;
                padding: 10px 24px; border: 1px solid #334155; }
            QTabBar::tab:selected { background: #0f172a; color: #f8fafc;
                border-bottom: 2px solid #3b82f6; }
            QLabel#title { font-size: 28px; font-weight: 700; color: #f9fafb; }
            QLabel#subtitle, QLabel#version, QLabel#footer { color: #94a3b8; }
            QLabel#bannerWarning { background: #78350f; color: #fef3c7;
                border: 1px solid #d97706; border-radius: 8px;
                font-size: 16px; font-weight: 700; padding: 8px; }
            QLabel#bannerReady { background: #064e3b; color: #d1fae5;
                border: 1px solid #10b981; border-radius: 8px;
                font-size: 16px; font-weight: 700; padding: 8px; }
            QLabel#bannerActive { background: #1e3a8a; color: #dbeafe;
                border: 1px solid #3b82f6; border-radius: 8px;
                font-size: 16px; font-weight: 700; padding: 8px; }
            QFrame#card { background: #1f2937; border: 1px solid #374151;
                border-radius: 10px; }
            QLabel#cardTitle { color: #f8fafc; font-size: 16px;
                font-weight: 700; padding-bottom: 4px; }
            QListWidget, QTextEdit { background: #0f172a; border: 1px solid #334155;
                border-radius: 6px; padding: 6px; selection-background-color: #2563eb; }
            QPushButton { background: #334155; border: 1px solid #475569;
                border-radius: 7px; padding: 10px 14px; font-weight: 600; }
            QPushButton:hover { background: #475569; }
            QPushButton:disabled { color: #64748b; background: #1e293b; }
            QPushButton#startButton { background: #047857; border-color: #10b981; }
            QPushButton#startButton:hover { background: #059669; }
            QPushButton#abortButton { background: #991b1b; border-color: #ef4444; }
            QPushButton#abortButton:hover { background: #b91c1c; }
            QPushButton#startButton:disabled { background: #134e4a;
                border-color: #1f6f64; color: #6b9f96; }
            QPushButton#abortButton:disabled { background: #4c1d1d;
                border-color: #7f1d1d; color: #9f6b6b; }
            """
        )

    def _poll(self) -> None:
        self._finish_background_tasks()
        if self._status_future is None:
            self._status_future = self.executor.submit(self.gateway.status)
        if self._stack_future is None:
            self._stack_future = self.executor.submit(self.stack.stack_status)

    def _finish_background_tasks(self) -> None:
        if self._status_future is not None and self._status_future.done():
            future, self._status_future = self._status_future, None
            try:
                self._status = future.result()
                self._last_gateway_ok_s = time.monotonic()
                self._render_status()
            except GatewayError as exc:
                self._render_gateway_error(str(exc))
        if self._stack_future is not None and self._stack_future.done():
            future, self._stack_future = self._stack_future, None
            try:
                self._stack_status = future.result()
                self._render_stack_status()
            except Exception as exc:
                self._append_message(f'Compose 상태 확인 실패: {exc}')
        if self._command_future is not None and self._command_future.done():
            future, self._command_future = self._command_future, None
            try:
                result = future.result()
                message = result.get('message') or result.get('error') or str(result)
                self._append_message(message)
                if not result.get('ok'):
                    QMessageBox.warning(self, '요청 거부', message)
            except Exception as exc:
                self._append_message(f'명령 실패: {exc}')
                QMessageBox.critical(self, '명령 실패', str(exc))
        if self._repository_future is not None and self._repository_future.done():
            future, self._repository_future = self._repository_future, None
            self.update_button.setEnabled(True)
            try:
                self._render_repository(future.result())
            except Exception as exc:
                self.footer.setText(f'원격 상태 확인 실패: {exc}')
                self.update_page.set_error(f'원격 상태 확인 실패: {exc}')
        if self._update_future is not None and self._update_future.done():
            future, self._update_future = self._update_future, None
            try:
                result: UpdateResult = future.result()
                self.update_page.set_update_complete(
                    '격리 테스트와 ROS 빌드를 통과했습니다.\n'
                    f'{result.previous_revision} → {result.revision}\n'
                    f'원격 커밋 {result.commit_count}개 적용 완료\n\n'
                    '“새 버전으로 앱 재시작”을 눌러 화면 로직을 전환하십시오.'
                )
                self.footer.setText(
                    f'업데이트 적용 완료 · {result.revision} · 앱 재시작 필요'
                )
            except Exception as exc:
                self.update_page.set_error(f'업데이트 실패: {exc}')
                QMessageBox.critical(self, '업데이트 실패', str(exc))

    def _render_status(self) -> None:
        status = self._status
        mission_state = str(status.get('mission_state', 'UNKNOWN'))
        connected = bool(status.get('mavros_connected'))
        armed = bool(status.get('armed'))
        landed = status.get('landed_state')
        landed_text = {0: '알 수 없음', 1: '지상', 2: '비행 중', 3: '이착륙 중'}.get(
            landed, '—'
        )
        self.flight_card.set_value('PX4 연결', '정상' if connected else '끊김')
        self.flight_card.set_value('ARM', 'ARMED' if armed else 'DISARMED')
        self.flight_card.set_value('비행 모드', status.get('flight_mode') or '—')
        self.flight_card.set_value('착륙 상태', landed_text)
        self.mission_card.set_value('상태', mission_state)
        panel = int(status.get('current_panel_id', -1))
        self.mission_card.set_value('현재 패널', str(panel) if panel >= 0 else '없음')
        self.mission_card.set_value(
            '시작 서비스', '정상' if status.get('start_service_ready') else '없음'
        )
        self.mission_card.set_value(
            '시작 잠금',
            '해제' if status.get('operator_start_enabled') else '잠김',
        )
        self.sensor_card.set_value(
            '배터리', display_value(status.get('battery_percent'), '%')
        )
        lidar = status.get('lidar_m')
        self.sensor_card.set_value(
            'LiDAR', '—' if lidar is None else f'{float(lidar):.2f} m'
        )
        self.sensor_card.set_value(
            '노트북 AI', '정상' if status.get('ai_healthy') else '비정상'
        )
        self.sensor_card.set_value(
            '고도 가드',
            '발동' if status.get('altitude_guard_triggered') else '정상',
        )
        self.spray_card.set_value('백엔드', status.get('spray_backend') or '—')
        self.spray_card.set_value(
            '물리 출력',
            '허용' if status.get('spray_output_enabled') else '차단',
        )
        self.spray_card.set_value(
            '미션 세션',
            '활성' if status.get('spray_session_enabled') else '비활성',
        )
        readiness = status.get('readiness', {})
        self.spray_card.set_value(
            '실제 분사 요구',
            '예' if readiness.get('require_live_spray') else '아니오',
        )
        failures = list(readiness.get('failures', []))
        if not status.get('operator_start_enabled'):
            failures.insert(0, '배포 설정에서 GUI 시작 명령이 잠겨 있음')
        self.blockers.clear()
        if failures:
            self.blockers.addItems([translate_failure(str(item)) for item in failures])
        else:
            self.blockers.addItem('모든 시작 조건 충족')
        result = str(status.get('mission_result') or '')
        if result and result != self._last_mission_result:
            self._last_mission_result = result
            self._append_message(f'미션 결과: {result}')

        active = mission_state not in INACTIVE_STATES and mission_state != 'UNKNOWN'
        ready = bool(status.get('start_allowed'))
        self.start_button.setEnabled(ready and self._command_future is None)
        self.abort_button.setEnabled(
            active and bool(status.get('abort_service_ready'))
            and self._command_future is None
        )
        self.stack_stop_button.setEnabled(stack_stop_is_safe(status))
        if active:
            self._set_banner(f'미션 진행 중 · {mission_state}', 'bannerActive')
        elif ready:
            self._set_banner('비행 시작 조건 충족 · 최종 현장 확인 필요', 'bannerReady')
        else:
            self._set_banner('비행 시작 잠김 · 차단 사유를 확인하십시오', 'bannerWarning')
        self.validation_page.render(
            status,
            self._stack_status,
            self._command_future is not None,
        )
        self.update_page.render_live_status(
            status,
            self._stack_status,
            self._update_future is not None
            or self._repository_future is not None,
        )

    def _render_gateway_error(self, error: str) -> None:
        if (
            self._last_gateway_ok_s is not None
            and time.monotonic() - self._last_gateway_ok_s < 2.0
        ):
            return
        self._set_banner('ROS 운영 게이트웨이 연결 안 됨', 'bannerWarning')
        self.start_button.setEnabled(False)
        self.abort_button.setEnabled(False)
        self.stack_stop_button.setEnabled(False)
        self.blockers.clear()
        self.blockers.addItem(error)
        self.validation_page.render_disconnected()
        self.update_page.render_disconnected()

    def _render_stack_status(self) -> None:
        if self._stack_status is None:
            return
        self.stack_start_button.setEnabled(
            not self._stack_status.mission_running
            and not self._stack_status.validation_mission_running
        )
        if self._status:
            self.validation_page.render(
                self._status,
                self._stack_status,
                self._command_future is not None,
            )
            self.update_page.render_live_status(
                self._status,
                self._stack_status,
                self._update_future is not None
                or self._repository_future is not None,
            )

    def _set_banner(self, text: str, object_name: str) -> None:
        self.banner.setText(text)
        self.banner.setObjectName(object_name)
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)

    def _start_stack(self) -> None:
        if self._command_future is not None:
            return
        self._append_message('잠금 기본값으로 ROS 스택을 시작합니다.')
        self._command_future = self.executor.submit(self._stack_command, 'start')

    def _stop_stack(self) -> None:
        if not stack_stop_is_safe(self._status):
            QMessageBox.warning(
                self,
                '정지 차단',
                'DISARM·지상·비활성 상태가 확인되지 않아 스택을 정지할 수 없습니다.',
            )
            return
        if QMessageBox.question(
            self,
            '미션 스택 정지',
            'MAVROS/QGC 연결은 유지하고 자율 미션 스택만 정지하시겠습니까?',
        ) != QMessageBox.Yes:
            return
        self._command_future = self.executor.submit(self._stack_command, 'stop')

    def _stack_command(self, command: str) -> dict:
        commands = {
            'start': self.stack.start_stack,
            'stop': self.stack.stop_mission_stack,
            'validation_start': self.stack.start_validation_stack,
            'validation_stop': self.stack.stop_validation_stack,
        }
        output = commands[command]()
        return {'ok': True, 'message': output or f'stack {command} complete'}

    def _start_validation_stack(self) -> None:
        if self._command_future is not None:
            return
        self._append_message('잠금 기본값으로 실기체 검증 스택을 시작합니다.')
        self._command_future = self.executor.submit(
            self._stack_command,
            'validation_start',
        )

    def _stop_validation_stack(self) -> None:
        if not validation_stack_stop_is_safe(self._status):
            QMessageBox.warning(
                self,
                '검증 스택 정지 차단',
                'DISARM·지상·검증 비활성 상태가 확인되지 않았습니다.',
            )
            return
        if QMessageBox.question(
            self,
            '검증 스택 정지',
            'MAVROS/QGC는 유지하고 1 m 검증 노드만 정지하시겠습니까?',
        ) != QMessageBox.Yes:
            return
        self._command_future = self.executor.submit(
            self._stack_command,
            'validation_stop',
        )

    def _request_validation_start(self, checklist: list[str]) -> bool:
        phrase, accepted = QInputDialog.getText(
            self,
            '실기체 검증 시작 확인',
            '이 명령은 기체를 자동 ARM하고 LiDAR 기준 1.1 m까지 이륙합니다.\n'
            '계류 상태를 다시 확인한 뒤 “1M 검증 시작”을 입력하십시오.',
        )
        if not accepted:
            return False
        if phrase.strip() != '1M 검증 시작':
            QMessageBox.warning(
                self,
                '확인 실패',
                '정확히 “1M 검증 시작”을 입력해야 합니다.',
            )
            return False
        self._command_future = self.executor.submit(
            self.gateway.start_validation,
            checklist,
        )
        return True

    def _request_validation_abort(self) -> None:
        if QMessageBox.question(
            self,
            '실기체 검증 중단',
            '검증 FSM에 중단과 AUTO.LAND를 요청하시겠습니까?\n'
            'QGC/PX4 비상조작을 대체하지 않습니다.',
        ) != QMessageBox.Yes:
            return
        self._command_future = self.executor.submit(
            self.gateway.abort_validation
        )

    def _request_start(self) -> None:
        phrase, accepted = QInputDialog.getText(
            self,
            '자율 청소 시작 확인',
            '프로펠러·비행구역·QGC 비상 개입·분사장치를 확인했습니다.\n'
            '시작하려면 아래에 “시작”을 입력하십시오.',
        )
        if not accepted:
            return
        if phrase.strip() != '시작':
            QMessageBox.warning(self, '확인 실패', '정확히 “시작”을 입력해야 합니다.')
            return
        self._command_future = self.executor.submit(self.gateway.start)

    def _request_abort(self) -> None:
        if QMessageBox.question(
            self,
            '미션 중단',
            '미션 중단과 미션 FSM의 착륙 절차를 요청하시겠습니까?\n'
            'QGC/PX4 비상조작을 대체하는 기능은 아닙니다.',
        ) != QMessageBox.Yes:
            return
        self._command_future = self.executor.submit(self.gateway.abort)

    def _check_repository(self, *, fetch: bool) -> None:
        if self._repository_future is not None or self._update_future is not None:
            return
        self.update_button.setEnabled(False)
        self.footer.setText('원격 저장소 확인 중…' if fetch else '로컬 버전 확인 중…')
        self.update_page.set_busy(
            True,
            'GitHub origin/main을 조회하고 있습니다…' if fetch
            else '로컬 저장소 버전을 확인하고 있습니다…',
        )
        self._repository_future = self.executor.submit(
            self.stack.repository_status,
            fetch=fetch,
        )

    def _render_repository(self, status: RepositoryStatus) -> None:
        self.validation_page.set_revision(status.revision)
        self.update_page.render_repository(status)
        dirty = '변경 있음' if status.dirty else '깨끗함'
        self.footer.setText(
            f'{status.branch}@{status.revision} · 작업트리 {dirty} · '
            f'원격보다 +{status.ahead}/-{status.behind} · '
            '업데이트 적용은 안전 검증된 릴리스 절차에서 수행'
        )

    def _show_update_page(self) -> None:
        self.tabs.setCurrentWidget(self.update_page)

    def _request_update(self) -> None:
        blockers = self.update_page.blockers_now()
        repository = self.update_page.repository
        if blockers or repository is None:
            QMessageBox.warning(
                self,
                '업데이트 차단',
                '\n'.join(blockers or ['원격 저장소 상태를 먼저 확인하십시오.']),
            )
            return
        phrase, accepted = QInputDialog.getText(
            self,
            '소프트웨어 업데이트 확인',
            f'origin/main {repository.remote_revision}까지 적용합니다.\n'
            '미션 스택은 정지되어 있어야 하며 업데이트 중 ARM하면 안 됩니다.\n'
            '계속하려면 “업데이트 적용”을 입력하십시오.',
        )
        if not accepted:
            return
        if phrase.strip() != '업데이트 적용':
            QMessageBox.warning(
                self,
                '확인 실패',
                '정확히 “업데이트 적용”을 입력해야 합니다.',
            )
            return
        self.update_page.set_busy(
            True,
            '원격 커밋을 격리 작업공간에서 테스트하고 있습니다.\n'
            '테스트 통과 후 DISARM·지상 상태를 다시 확인하고 적용합니다.\n'
            '완료될 때까지 기체를 ARM하지 마십시오.',
        )
        self._update_future = self.executor.submit(
            self.stack.apply_remote_update,
            repository.remote_revision,
            self._live_update_blockers,
        )

    def _live_update_blockers(self) -> list[str]:
        status = self.gateway.status()
        stack_status = self.stack.stack_status()
        repository = self.stack.repository_status(fetch=False)
        return software_update_blockers(status, stack_status, repository)

    def _restart_app(self) -> None:
        launcher = self.project_root / 'tools' / 'start_pi_operator_app.sh'
        try:
            subprocess.Popen(
                [str(launcher)],
                cwd=self.project_root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            QMessageBox.critical(self, '앱 재시작 실패', str(exc))
            return
        QTimer.singleShot(300, QApplication.instance().quit)

    def _append_message(self, message: str) -> None:
        timestamp = time.strftime('%H:%M:%S')
        prior = self.result_text.toPlainText().strip()
        text = f'[{timestamp}] {message}'
        self.result_text.setPlainText(f'{prior}\n{text}'.strip())
        self.result_text.moveCursor(QTextCursor.End)

    def closeEvent(self, event) -> None:
        """Stop only GUI helper threads; never stop a flight process."""
        if self._update_future is not None:
            QMessageBox.warning(
                self,
                '업데이트 진행 중',
                '저장소 업데이트가 끝난 뒤 앱을 종료하십시오.',
            )
            event.ignore()
            return
        self.refresh_timer.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)
        event.accept()


def configure_application(app: QApplication) -> None:
    """Set a consistent application font and dark palette."""
    app.setApplicationName('DA-DAKA Operator')
    app.setOrganizationName('DA-DAKA')
    font = QFont(app.font())
    font.setPointSize(10)
    app.setFont(font)
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor('#111827'))
    palette.setColor(QPalette.WindowText, QColor('#e5e7eb'))
    app.setPalette(palette)
