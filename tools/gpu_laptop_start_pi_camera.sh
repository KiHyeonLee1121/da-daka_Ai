#!/usr/bin/env bash
set -euo pipefail

# Copy this file to the GPU laptop and run it there. It connects to the
# Raspberry Pi over SSH and starts the Pi camera/edge link toward the laptop.
PI_IP="${PI_IP:-10.205.180.181}"
PI_USER="${PI_USER:-kihyeon}"
LAPTOP_IP="${LAPTOP_IP:-10.205.180.126}"
PI_PROJECT="${PI_PROJECT:-/home/kihyeon/da-daka_Ai}"
PI_WORKSPACE="${PI_WORKSPACE:-${PI_PROJECT}/ros2_ws}"
PI_LAUNCHER="${PI_LAUNCHER:-${PI_PROJECT}/tools/edge_gpu_link.py}"

finish() {
    local exit_code=$?
    if [[ ${exit_code} -ne 0 && ${exit_code} -ne 130 ]]; then
        echo
        echo "Pi 카메라 전송을 시작하지 못했습니다." >&2
        read -r -p "Enter를 누르면 종료합니다." || true
    fi
    exit "${exit_code}"
}
trap finish EXIT

validate_ipv4() {
    python3 - "$1" <<'PY'
import ipaddress
import sys

address = ipaddress.ip_address(sys.argv[1])
if address.version != 4 or address.is_loopback or address.is_multicast:
    raise SystemExit(1)
PY
}

echo "DA-DAKA Raspberry Pi 카메라 → GPU 노트북 전송 시작"
echo "Raspberry Pi: ${PI_USER}@${PI_IP}"
echo "영상 목적지: ${LAPTOP_IP}:5600/udp"
echo

if ! validate_ipv4 "${PI_IP}" || ! validate_ipv4 "${LAPTOP_IP}"; then
    echo "오류: PI_IP 또는 LAPTOP_IP가 올바르지 않습니다." >&2
    exit 1
fi

if ! ping -c 1 -W 2 "${PI_IP}" >/dev/null 2>&1; then
    echo "오류: Raspberry Pi ${PI_IP}에 연결할 수 없습니다." >&2
    echo "Pi와 노트북이 같은 현장 LAN에 연결됐는지 확인하세요." >&2
    exit 1
fi

echo "Pi 연결 확인 완료"
echo "SSH로 Pi 카메라 송출을 시작합니다."
echo "이 터미널을 유지하고, 전송을 끝낼 때 Ctrl+C를 누르세요."
echo

printf -v remote_command \
    "cd %q && exec python3 %q --laptop-ip %q --workspace %q" \
    "${PI_PROJECT}" "${PI_LAUNCHER}" "${LAPTOP_IP}" "${PI_WORKSPACE}"

ssh -tt \
    -o BatchMode=yes \
    -o ConnectTimeout=5 \
    -o ServerAliveInterval=10 \
    -o ServerAliveCountMax=3 \
    -o StrictHostKeyChecking=accept-new \
    "${PI_USER}@${PI_IP}" \
    "${remote_command}"
