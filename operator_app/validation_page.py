"""Dedicated Qt page for staged real-aircraft flight validation."""

from pathlib import Path
from typing import Callable, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from operator_app.stack_manager import StackStatus, validation_stack_stop_is_safe
from operator_app.ui_components import StatusCard, display_value, translate_failure
from operator_app.validation_history import ValidationHistory


CHECKLIST_ITEMS = (
    ('flight_area_clear', '비행구역 3 m 반경과 상부가 비어 있음'),
    ('tether_installed', '계류줄과 기체 고정 상태를 확인함'),
    ('propellers_inspected', '프로펠러·모터·프레임 체결을 확인함'),
    ('qgc_emergency_ready', 'QGC Hold/Land와 수동 개입 수단이 준비됨'),
    ('observer_ready', '조종자 외 안전 관찰자가 위치함'),
    ('spray_power_isolated', '펌프·밸브 전원을 물리적으로 분리함'),
)

VALIDATION_STAGES = (
    'PRECHECK',
    'ARMING',
    'TAKEOFF / HOVER',
    'CHECK_SENSOR',
    'ENABLE / OFFBOARD',
    'DISTANCE_CONTROL',
    'TARGET_HOLD',
    'LOITER_HANDOVER',
    'AUTO_LAND',
    'WAIT_DISARM',
    'COMPLETE',
)

STATE_STAGE = {
    'PRECHECK': 0,
    'ARMING': 1,
    'TAKEOFF': 2,
    'PRESTREAM_SETPOINT': 2,
    'WAIT_HOVER': 2,
    'CHECK_SENSOR': 3,
    'ENABLE_DISTANCE_CONTROL': 4,
    'ENTER_OFFBOARD': 4,
    'DISTANCE_CONTROL': 5,
    'TARGET_HOLD': 6,
    'LOITER_HANDOVER': 7,
    'AUTO_LAND': 8,
    'WAIT_DISARM': 9,
    'COMPLETE': 10,
}


class ValidationPage(QWidget):
    """Render the 1 m tethered validation workflow and its hard gates."""

    def __init__(
        self,
        history_path: Path,
        *,
        start_stack: Callable[[], None],
        stop_stack: Callable[[], None],
        start_validation: Callable[[list[str]], bool],
        abort_validation: Callable[[], None],
    ) -> None:
        """Build the page and bind only high-level operator callbacks."""
        super().__init__()
        self._start_stack_callback = start_stack
        self._stop_stack_callback = stop_stack
        self._start_validation_callback = start_validation
        self._abort_validation_callback = abort_validation
        self._history = ValidationHistory(history_path)
        self._revision = 'unknown'
        self._last_result = ''
        self._check_boxes: dict[str, QCheckBox] = {}
        self._build_ui()
        self._render_history()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)
        title = QLabel('실기체 비행 검증 · 계류 1 m 프로파일')
        title.setObjectName('title')
        subtitle = QLabel(
            'LiDAR 1.1 m 이륙 → 1.0 m 안정화 → Loiter 인계 → 자동 착륙'
        )
        subtitle.setObjectName('subtitle')
        root.addWidget(title)
        root.addWidget(subtitle)

        self.banner = QLabel('검증 gateway 연결 대기 중')
        self.banner.setObjectName('bannerWarning')
        self.banner.setAlignment(Qt.AlignCenter)
        self.banner.setMinimumHeight(44)
        root.addWidget(self.banner)

        cards = QGridLayout()
        self.flight_card = StatusCard(
            '기체 상태', ('PX4 연결', 'ARM', '비행 모드', '착륙 상태')
        )
        self.profile_card = StatusCard(
            '검증 프로파일', ('상태', '이륙 목표', '거리 목표', '승인 잠금')
        )
        self.data_card = StatusCard(
            '검증 데이터', ('배터리', 'LiDAR', '시작 서비스', '고도 가드')
        )
        cards.addWidget(self.flight_card, 0, 0)
        cards.addWidget(self.profile_card, 0, 1)
        cards.addWidget(self.data_card, 0, 2)
        root.addLayout(cards)

        content = QHBoxLayout()
        left = QFrame()
        left.setObjectName('card')
        left_layout = QVBoxLayout(left)
        checklist_title = QLabel('현장 필수 체크리스트')
        checklist_title.setObjectName('cardTitle')
        left_layout.addWidget(checklist_title)
        for identifier, text in CHECKLIST_ITEMS:
            checkbox = QCheckBox(text)
            checkbox.stateChanged.connect(self._update_start_button)
            self._check_boxes[identifier] = checkbox
            left_layout.addWidget(checkbox)
        blockers_title = QLabel('검증 차단 사유')
        blockers_title.setObjectName('cardTitle')
        left_layout.addWidget(blockers_title)
        self.blockers = QListWidget()
        left_layout.addWidget(self.blockers, 1)
        content.addWidget(left, 3)

        center = QFrame()
        center.setObjectName('card')
        center_layout = QVBoxLayout(center)
        timeline_title = QLabel('자동 검증 진행 단계')
        timeline_title.setObjectName('cardTitle')
        center_layout.addWidget(timeline_title)
        self.progress = QProgressBar()
        self.progress.setRange(0, len(VALIDATION_STAGES))
        self.progress.setValue(0)
        center_layout.addWidget(self.progress)
        self.timeline = QListWidget()
        for state in VALIDATION_STAGES:
            self.timeline.addItem(QListWidgetItem(state))
        center_layout.addWidget(self.timeline, 1)
        content.addWidget(center, 2)

        right = QFrame()
        right.setObjectName('card')
        right_layout = QVBoxLayout(right)
        history_title = QLabel('검증 결과 기록')
        history_title.setObjectName('cardTitle')
        right_layout.addWidget(history_title)
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        right_layout.addWidget(self.result_text)
        content.addWidget(right, 3)
        root.addLayout(content, 1)

        controls = QHBoxLayout()
        self.stack_start_button = QPushButton('검증 스택 시작')
        self.stack_start_button.clicked.connect(self._start_stack_callback)
        self.stack_stop_button = QPushButton('검증 스택 정지')
        self.stack_stop_button.clicked.connect(self._stop_stack_callback)
        self.start_button = QPushButton('계류 1 m 검증 시작')
        self.start_button.setObjectName('startButton')
        self.start_button.clicked.connect(self._request_start)
        self.abort_button = QPushButton('검증 중단·착륙 요청')
        self.abort_button.setObjectName('abortButton')
        self.abort_button.clicked.connect(self._abort_validation_callback)
        controls.addWidget(self.stack_start_button)
        controls.addWidget(self.stack_stop_button)
        controls.addStretch(1)
        controls.addWidget(self.start_button)
        controls.addWidget(self.abort_button)
        root.addLayout(controls)

        warning = QLabel(
            '이 페이지는 QGC/조종기 비상조작을 대체하지 않습니다. '
            '첫 실행은 반드시 계류 상태와 안전 관찰자 동반 조건에서 수행하십시오.'
        )
        warning.setWordWrap(True)
        warning.setObjectName('footer')
        root.addWidget(warning)

    def set_revision(self, revision: str) -> None:
        """Associate future validation records with a source revision."""
        self._revision = revision

    def render(
        self,
        status: dict,
        stack_status: Optional[StackStatus],
        busy: bool,
    ) -> None:
        """Render a gateway snapshot and recompute every validation gate."""
        state = str(status.get('validation_state', 'UNKNOWN'))
        readiness = status.get('validation_readiness', {})
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
        self.profile_card.set_value('상태', state)
        self.profile_card.set_value(
            '이륙 목표',
            display_value(readiness.get('takeoff_distance_m'), ' m'),
        )
        self.profile_card.set_value(
            '거리 목표',
            display_value(readiness.get('target_distance_m'), ' m'),
        )
        self.profile_card.set_value(
            '승인 잠금',
            '해제' if status.get('validation_start_enabled') else '잠김',
        )
        self.data_card.set_value(
            '배터리', display_value(status.get('battery_percent'), '%')
        )
        lidar = status.get('lidar_m')
        self.data_card.set_value(
            'LiDAR', '—' if lidar is None else f'{float(lidar):.2f} m'
        )
        self.data_card.set_value(
            '시작 서비스',
            '정상' if status.get('validation_start_service_ready') else '없음',
        )
        self.data_card.set_value(
            '고도 가드',
            '발동' if status.get('altitude_guard_triggered') else '정상',
        )

        failures = list(readiness.get('failures', []))
        if not status.get('validation_start_enabled'):
            failures.insert(0, '배포 설정에서 실기체 검증 시작이 잠겨 있음')
        self.blockers.clear()
        self.blockers.addItems(
            [translate_failure(str(item)) for item in failures]
            or ['ROS 준비조건 충족 · 현장 체크리스트 확인 필요']
        )
        self._render_timeline(state)

        active = state not in {'UNKNOWN', 'IDLE', 'COMPLETE', 'ABORT'}
        allowed = bool(status.get('validation_start_allowed'))
        self._gateway_allowed = allowed
        self._busy = busy
        self._update_start_button()
        self.abort_button.setEnabled(
            active
            and bool(status.get('validation_abort_service_ready'))
            and not busy
        )
        self.stack_stop_button.setEnabled(
            validation_stack_stop_is_safe(status) and not busy
        )
        if stack_status is not None:
            conflict = stack_status.mission_running
            self.stack_start_button.setEnabled(
                not stack_status.validation_mission_running
                and not conflict
                and not busy
            )
        if active:
            self._set_banner(f'실기체 검증 진행 중 · {state}', 'bannerActive')
        elif allowed:
            self._set_banner(
                'ROS 검증 조건 충족 · 현장 체크리스트 확인 필요',
                'bannerReady',
            )
        else:
            self._set_banner('실기체 검증 시작 잠김', 'bannerWarning')

        result = str(status.get('validation_result') or '')
        if result and result != self._last_result:
            self._last_result = result
            if self._history.append_terminal(result, status, self._revision):
                self._render_history()

    def render_disconnected(self) -> None:
        """Disable flight controls when the local gateway is unavailable."""
        self._gateway_allowed = False
        self._busy = False
        self._update_start_button()
        self.abort_button.setEnabled(False)
        self.stack_stop_button.setEnabled(False)
        self._set_banner('검증 gateway 연결 안 됨', 'bannerWarning')

    def _request_start(self) -> None:
        checklist = [
            identifier
            for identifier, checkbox in self._check_boxes.items()
            if checkbox.isChecked()
        ]
        if len(checklist) != len(CHECKLIST_ITEMS):
            QMessageBox.warning(
                self,
                '체크리스트 미완료',
                '모든 현장 안전 항목을 직접 확인해야 합니다.',
            )
            return
        if self._start_validation_callback(checklist):
            for checkbox in self._check_boxes.values():
                checkbox.setChecked(False)

    def _update_start_button(self) -> None:
        checked = all(item.isChecked() for item in self._check_boxes.values())
        self.start_button.setEnabled(
            bool(getattr(self, '_gateway_allowed', False))
            and checked
            and not bool(getattr(self, '_busy', False))
        )

    def _render_timeline(self, state: str) -> None:
        if state in STATE_STAGE:
            current = STATE_STAGE[state]
            self.progress.setValue(current + 1)
        else:
            current = -1
            self.progress.setValue(0)
        for index in range(self.timeline.count()):
            item = self.timeline.item(index)
            if index < current:
                item.setForeground(QColor('#6ee7b7'))
            elif index == current:
                item.setForeground(QColor('#60a5fa'))
            else:
                item.setForeground(QColor('#94a3b8'))

    def _render_history(self) -> None:
        records = self._history.load(limit=20)
        lines = []
        for record in reversed(records):
            result = str(record.get('result', ''))
            outcome = '성공' if result.startswith('SUCCESS') else '중단/실패'
            recorded_at = record.get('recorded_at', '')
            revision = record.get('revision', 'unknown')
            lines.append(
                f'{recorded_at} · {outcome}\n'
                f'  {result}\n'
                f'  revision={revision}'
            )
        self.result_text.setPlainText('\n\n'.join(lines) or '아직 검증 기록이 없습니다.')

    def _set_banner(self, text: str, object_name: str) -> None:
        self.banner.setText(text)
        self.banner.setObjectName(object_name)
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)
