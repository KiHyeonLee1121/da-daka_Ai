#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv="${DA_DAKA_VENV:-${repository}/.venv}"
panel_manifest="${DA_DAKA_PANEL_MANIFEST:-${repository}/models/panel_detection_v1/model.json}"
dirt_manifest="${DA_DAKA_DIRT_MANIFEST:-${repository}/models/dirt_segmentation_v1/model.json}"
default_pi_ip="${PI_IP:-10.205.180.181}"

show_error() {
    local message="$1"
    if command -v zenity >/dev/null 2>&1; then
        zenity --error --title='DA-DAKA GPU AI 모니터' \
            --text="${message}" || true
    fi
    echo "오류: ${message}" >&2
}

if [[ ! -x "${repository}/tools/start_live_ai_monitor.sh" ]]; then
    show_error "통합 모니터 실행 파일이 없습니다:\n${repository}/tools/start_live_ai_monitor.sh"
    exit 1
fi
if [[ ! -x "${venv}/bin/python" ]]; then
    show_error "검증된 GPU Python 환경이 없습니다:\n${venv}"
    exit 1
fi
if [[ ! -f "${panel_manifest}" || ! -f "${dirt_manifest}" ]]; then
    show_error "최종 학습 모델 bundle이 없습니다.\n\n필요 파일:\n${panel_manifest}\n${dirt_manifest}\n\nplaceholder 모델로 production 모니터를 시작하지 않습니다."
    exit 2
fi

if command -v zenity >/dev/null 2>&1; then
    pi_ip="$(zenity --entry \
        --title='DA-DAKA GPU 실시간 AI 모니터' \
        --text='현재 Raspberry Pi IPv4 주소를 입력하세요.' \
        --entry-text="${default_pi_ip}")" || exit 0
else
    read -r -p "Raspberry Pi IPv4 [${default_pi_ip}]: " pi_ip
    pi_ip="${pi_ip:-${default_pi_ip}}"
fi

echo '파란 박스: 태양광 패널'
echo '초록 박스: 오염 component'
echo '이 응용프로그램은 관찰 전용이며 비행·분사 명령을 보내지 않습니다.'
echo

DA_DAKA_VENV="${venv}" \
    exec "${repository}/tools/start_live_ai_monitor.sh" \
    --pi-ip "${pi_ip}" \
    --panel-manifest "${panel_manifest}" \
    --dirt-manifest "${dirt_manifest}"
