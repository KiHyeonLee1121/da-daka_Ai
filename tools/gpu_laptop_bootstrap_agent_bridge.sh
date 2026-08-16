#!/usr/bin/env bash
set -euo pipefail

# Run this once on the GPU laptop. It retrieves the bridge from the Pi over the
# same SSH path used for camera control, configures the GPU identity, and shows
# the first unread handoff message.
PI_IP="${PI_IP:-172.20.10.5}"
PI_USER="${PI_USER:-kihyeon}"
PI_BRIDGE="${PI_BRIDGE:-/home/kihyeon/.local/bin/dadaka-agent}"
PI_CONSOLE="${PI_CONSOLE:-/home/kihyeon/.local/bin/dadaka-agent-console}"
LOCAL_INSTALL_DIR="${HOME}/.local/bin"
LOCAL_BRIDGE="${LOCAL_INSTALL_DIR}/dadaka-agent"
LOCAL_CONSOLE="${LOCAL_INSTALL_DIR}/dadaka-agent-console"
GPU_PROJECT="${GPU_PROJECT:-${HOME}/da-daka_Ai}"
temporary_bridge=""
temporary_console=""

finish() {
    local exit_code=$?
    if [[ -n ${temporary_bridge} ]]; then
        rm -f -- "${temporary_bridge}"
    fi
    if [[ -n ${temporary_console} ]]; then
        rm -f -- "${temporary_console}"
    fi
    if [[ ${exit_code} -ne 0 && -t 0 ]]; then
        echo >&2
        echo "Codex 메시지 브리지 설치에 실패했습니다." >&2
        read -r -p "Enter를 누르면 종료합니다." || true
    fi
    exit "${exit_code}"
}
trap finish EXIT

echo "DA-DAKA GPU 노트북 Codex 메시지 브리지 설치"
echo "중앙 Pi: ${PI_USER}@${PI_IP}"
echo

install -d -m 0755 "${LOCAL_INSTALL_DIR}"
temporary_bridge=$(mktemp "${LOCAL_INSTALL_DIR}/.dadaka-agent.XXXXXX")
temporary_console=$(mktemp "${LOCAL_INSTALL_DIR}/.dadaka-agent-console.XXXXXX")

scp \
    -o BatchMode=yes \
    -o ConnectTimeout=5 \
    -o StrictHostKeyChecking=accept-new \
    "${PI_USER}@${PI_IP}:${PI_BRIDGE}" \
    "${temporary_bridge}"

scp \
    -o BatchMode=yes \
    -o ConnectTimeout=5 \
    -o StrictHostKeyChecking=accept-new \
    "${PI_USER}@${PI_IP}:${PI_CONSOLE}" \
    "${temporary_console}"

install -m 0755 "${temporary_bridge}" "${LOCAL_BRIDGE}"
install -m 0755 "${temporary_console}" "${LOCAL_CONSOLE}"
"${LOCAL_BRIDGE}" init \
    --name gpu \
    --hub "${PI_USER}@${PI_IP}" \
    --remote-command "${PI_BRIDGE}"

python3 -c 'import tkinter; print("Tk", tkinter.TkVersion)'
"${LOCAL_CONSOLE}" \
    --configure-role gpu \
    --hub-address "${PI_IP}" \
    --ssh-user "${PI_USER}" \
    --project-dir "${GPU_PROJECT}" \
    --auto-start true
"${LOCAL_CONSOLE}" --install-desktop

echo
"${LOCAL_BRIDGE}" ping
echo
echo "설치 완료. Pi가 보낸 읽지 않은 메시지:"
"${LOCAL_BRIDGE}" inbox

bootstrap_id=$(
    "${LOCAL_BRIDGE}" inbox --json | python3 -c '
import json
import sys

for message in json.load(sys.stdin):
    if message.get("task") == "agent-bridge-bootstrap":
        print(message["id"])
        break
'
)
if [[ -n ${bootstrap_id} ]]; then
    "${LOCAL_BRIDGE}" reply "${bootstrap_id}" \
        --task agent-bridge-bootstrap \
        --status complete \
        "GPU 노트북 브리지 설치 및 Pi SSH 왕복 연결 확인 완료 ($(hostname))"
    echo "Pi에 설치 완료 회신을 보냈습니다."
fi

echo
echo "앞으로 사용할 명령: dadaka-agent receive"
echo "앱 바로가기: ${HOME}/Desktop/DA-DAKA-Agent-Console.desktop"
if [[ -n ${DISPLAY:-} ]]; then
    install -d -m 0700 "${HOME}/.local/state/dadaka-agent-console"
    nohup "${LOCAL_CONSOLE}" \
        >"${HOME}/.local/state/dadaka-agent-console-launch.log" 2>&1 &
fi
