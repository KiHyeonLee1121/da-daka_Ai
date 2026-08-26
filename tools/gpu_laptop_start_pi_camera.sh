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
DA_DAKA_NONINTERACTIVE="${DA_DAKA_NONINTERACTIVE:-0}"
DA_DAKA_CAMERA_ONLY="${DA_DAKA_CAMERA_ONLY:-0}"
VIDEO_WIDTH="${VIDEO_WIDTH:-1280}"
VIDEO_HEIGHT="${VIDEO_HEIGHT:-720}"
VIDEO_FRAMERATE="${VIDEO_FRAMERATE:-20}"
VIDEO_BITRATE="${VIDEO_BITRATE:-4000000}"

finish() {
    local exit_code=$?
    if [[ ${exit_code} -ne 0 && ${exit_code} -ne 130 ]]; then
        echo
        echo "Pi 카메라 전송을 시작하지 못했습니다." >&2
        if [[ "${DA_DAKA_NONINTERACTIVE}" != "1" ]]; then
            read -r -p "Enter를 누르면 종료합니다." || true
        fi
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
if [[ "${DA_DAKA_CAMERA_ONLY}" == "1" ]]; then
    echo "관찰 전용 camera-only 모드: ROS control/result process를 시작하지 않습니다."
fi
echo "이 터미널을 유지하고, 전송을 끝낼 때 Ctrl+C를 누르세요."
echo

if [[ "${DA_DAKA_CAMERA_ONLY}" == "1" ]]; then
    video_output="udp://${LAPTOP_IP}:5600?pkt_size=1316"
    printf -v remote_command \
        "exec rpicam-vid -t 0 -n --codec libav --libav-format mpegts --low-latency --width %q --height %q --framerate %q --bitrate %q -o %q" \
        "${VIDEO_WIDTH}" "${VIDEO_HEIGHT}" "${VIDEO_FRAMERATE}" \
        "${VIDEO_BITRATE}" "${video_output}"
else
    printf -v remote_command \
        "cd %q && exec python3 %q --laptop-ip %q --workspace %q" \
        "${PI_PROJECT}" "${PI_LAUNCHER}" "${LAPTOP_IP}" "${PI_WORKSPACE}"
fi

ssh -tt \
    -o BatchMode=yes \
    -o ConnectTimeout=5 \
    -o ServerAliveInterval=10 \
    -o ServerAliveCountMax=3 \
    -o StrictHostKeyChecking=accept-new \
    "${PI_USER}@${PI_IP}" \
    "${remote_command}"
