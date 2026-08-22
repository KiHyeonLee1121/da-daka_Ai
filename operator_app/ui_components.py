"""Shared Qt status components and operator-facing value formatting."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFormLayout, QFrame, QLabel, QVBoxLayout


def display_value(value, suffix: str = '') -> str:
    """Format an optional numeric value for an operator label."""
    if value is None:
        return '—'
    if isinstance(value, float):
        return f'{value:.1f}{suffix}'
    return f'{value}{suffix}'


def translate_failure(value: str) -> str:
    """Translate common preflight failures while preserving technical detail."""
    translations = {
        'configuration approval is locked': '기체 구성 승인이 잠겨 있음',
        'calibration approval is locked': '실측 보정 승인이 잠겨 있음',
        'flight validation approval is locked': '실기체 검증 승인이 잠겨 있음',
        'MAVROS disconnected': 'MAVROS/PX4 연결 끊김',
        'vehicle already armed': '기체가 이미 ARM 상태임',
        'local pose/velocity telemetry stale': '위치/속도 정보가 오래됨',
        'MAVROS pose or velocity telemetry unavailable': (
            'MAVROS 위치/속도 정보 사용 불가'
        ),
        'distance sensor unavailable': 'LiDAR 거리 센서 사용 불가',
        'distance sensor unavailable or invalid': 'LiDAR 거리 센서 값 비정상',
        'laptop AI heartbeat is not healthy': '노트북 AI heartbeat 비정상',
        'launch Local XYZ reference unavailable': '이륙 기준 좌표가 없음',
        'live spray output is unavailable or blocked': '실제 분사 출력이 잠겨 있음',
        'spray status is unavailable or stale': '분사장치 상태를 확인할 수 없음',
        'mission readiness has not been received': '미션 준비 상태를 받지 못함',
        'validation readiness has not been received': '검증 준비 상태를 받지 못함',
    }
    return translations.get(value, value)


class StatusCard(QFrame):
    """Small reusable panel of labeled operator values."""

    def __init__(self, title: str, fields: tuple[str, ...]) -> None:
        """Create a titled card with a fixed set of value labels."""
        super().__init__()
        self.setObjectName('card')
        layout = QVBoxLayout(self)
        title_label = QLabel(title)
        title_label.setObjectName('cardTitle')
        layout.addWidget(title_label)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        self.values = {}
        for field in fields:
            value = QLabel('—')
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.values[field] = value
            form.addRow(field, value)
        layout.addLayout(form)

    def set_value(self, field: str, value: str) -> None:
        """Update one known field."""
        self.values[field].setText(value)
