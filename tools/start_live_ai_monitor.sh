#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv="${DA_DAKA_VENV:-${repository}/.venv}"
config="${DA_DAKA_CONFIG:-${repository}/laptop_ai/config/laptop_ai.yaml}"
camera_launcher="${DA_DAKA_CAMERA_LAUNCHER:-${repository}/tools/gpu_laptop_start_pi_camera.sh}"
panel_manifest="${DA_DAKA_PANEL_MANIFEST:-${repository}/models/panel_detection_v1/model.json}"
dirt_manifest="${DA_DAKA_DIRT_MANIFEST:-${repository}/models/dirt_segmentation_v1/model.json}"
pi_ip="${PI_IP:-}"
pi_user="${PI_USER:-kihyeon}"
laptop_ip="${LAPTOP_IP:-}"
pi_project="${PI_PROJECT:-/home/kihyeon/da-daka_Ai-main-integration-20260816-031902}"
fullscreen=false
artifact_test=false
start_camera=true
camera_pid=''

usage() {
    cat <<'EOF'
Usage: tools/start_live_ai_monitor.sh --pi-ip <PI_IP> [options]

Starts the existing Pi camera SSH launcher and an observe-only laptop GPU
window. Panel boxes are blue and Dirt component boxes are green on every
decoded frame. No flight, mission, GPIO, spray, or approval command is sent.

Options:
  --pi-ip ADDRESS       Raspberry Pi address (required)
  --laptop-ip ADDRESS   stream destination; auto-selected from the Pi route
  --pi-user USER        SSH user (default: kihyeon)
  --pi-project PATH     project path on the Pi
  --camera-launcher PATH existing laptop-side Pi camera SSH script
  --panel-manifest PATH approved Panel bundle manifest
  --dirt-manifest PATH approved Dirt bundle manifest
  --config PATH         laptop AI YAML configuration
  --fullscreen          open the inference window fullscreen
  --no-start-camera     receive an already-running UDP 5600 stream
  --artifact-test       explicit no-flight/no-spray test-artifact mode
  -h, --help            show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --pi-ip) pi_ip="${2:?--pi-ip requires an address}"; shift 2 ;;
        --laptop-ip) laptop_ip="${2:?--laptop-ip requires an address}"; shift 2 ;;
        --pi-user) pi_user="${2:?--pi-user requires a value}"; shift 2 ;;
        --pi-project) pi_project="${2:?--pi-project requires a path}"; shift 2 ;;
        --camera-launcher) camera_launcher="${2:?--camera-launcher requires a path}"; shift 2 ;;
        --panel-manifest) panel_manifest="${2:?--panel-manifest requires a path}"; shift 2 ;;
        --dirt-manifest) dirt_manifest="${2:?--dirt-manifest requires a path}"; shift 2 ;;
        --config) config="${2:?--config requires a path}"; shift 2 ;;
        --fullscreen) fullscreen=true; shift ;;
        --no-start-camera) start_camera=false; shift ;;
        --artifact-test) artifact_test=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ -z "${pi_ip}" ]]; then
    echo 'ERROR: provide the current Raspberry Pi address with --pi-ip.' >&2
    exit 2
fi
if [[ ! -x "${venv}/bin/python" ]]; then
    echo "ERROR: known-good Python environment is missing: ${venv}" >&2
    exit 2
fi
for required_file in "${config}" "${panel_manifest}" "${dirt_manifest}"; do
    if [[ ! -f "${required_file}" ]]; then
        echo "ERROR: required file is missing: ${required_file}" >&2
        exit 2
    fi
done
if [[ "${start_camera}" == true && ! -x "${camera_launcher}" ]]; then
    echo "ERROR: Pi camera launcher is missing or not executable: ${camera_launcher}" >&2
    exit 2
fi

validate_ipv4() {
    "${venv}/bin/python" - "$1" <<'PY'
import ipaddress
import sys
value = ipaddress.ip_address(sys.argv[1])
if value.version != 4 or value.is_loopback or value.is_multicast or value.is_unspecified:
    raise SystemExit(1)
PY
}

if ! validate_ipv4 "${pi_ip}"; then
    echo "ERROR: invalid Raspberry Pi IPv4 address: ${pi_ip}" >&2
    exit 2
fi
if [[ -z "${laptop_ip}" ]]; then
    laptop_ip="$("${venv}/bin/python" - "${pi_ip}" <<'PY'
import socket
import sys
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    sock.connect((sys.argv[1], 9))
    print(sock.getsockname()[0])
finally:
    sock.close()
PY
)"
fi
if ! validate_ipv4 "${laptop_ip}"; then
    echo "ERROR: invalid Laptop IPv4 address: ${laptop_ip}" >&2
    exit 2
fi

export PYTHONPATH="${repository}/laptop_ai${PYTHONPATH:+:${PYTHONPATH}}"

echo 'DA-DAKA GPU 실시간 AI 모니터'
echo "Project: ${repository}"
echo "Python: ${venv}"
echo "Pi: ${pi_user}@${pi_ip}"
echo "Video: ${pi_ip} -> ${laptop_ip}:5600/udp"
echo "Panel manifest: ${panel_manifest}"
echo "Dirt manifest: ${dirt_manifest}"
echo "Mode: $([[ ${artifact_test} == true ]] && echo ARTIFACT TEST || echo PRODUCTION-APPROVED MODELS ONLY)"
echo 'Safety: OBSERVE ONLY; no flight, mission, GPIO, spray, or approval command.'
echo

"${venv}/bin/python" -m laptop_ai.nvidia_check
verify_args=()
monitor_args=()
if [[ "${artifact_test}" == true ]]; then
    verify_args+=(--allow-test-only)
    monitor_args+=(--artifact-test)
else
    verify_args+=(--require-deployment-approved)
fi
"${venv}/bin/python" -m laptop_ai.verify_pipeline \
    --panel-manifest "${panel_manifest}" \
    --dirt-manifest "${dirt_manifest}" \
    "${verify_args[@]}"

cleanup() {
    local exit_code=$?
    trap - EXIT INT TERM
    if [[ -n "${camera_pid}" ]] && kill -0 "${camera_pid}" 2>/dev/null; then
        kill -INT "${camera_pid}" 2>/dev/null || true
        wait "${camera_pid}" 2>/dev/null || true
    fi
    exit "${exit_code}"
}
trap cleanup EXIT INT TERM

if [[ "${start_camera}" == true ]]; then
    echo 'Starting the Raspberry Pi camera over SSH...'
    DA_DAKA_NONINTERACTIVE=1 \
    DA_DAKA_CAMERA_ONLY=1 \
    PI_IP="${pi_ip}" \
    PI_USER="${pi_user}" \
    LAPTOP_IP="${laptop_ip}" \
    PI_PROJECT="${pi_project}" \
        "${camera_launcher}" &
    camera_pid=$!
    sleep 1
    if ! kill -0 "${camera_pid}" 2>/dev/null; then
        wait "${camera_pid}" || true
        echo 'ERROR: Pi camera launcher stopped before the monitor opened.' >&2
        exit 1
    fi
fi

if [[ "${fullscreen}" == true ]]; then
    monitor_args+=(--fullscreen)
fi
echo 'Opening frame-by-frame inference window. Q/ESC=quit, S=screenshot, F=fullscreen.'
"${venv}/bin/python" -m laptop_ai.live_monitor_app \
    --config "${config}" \
    --pi-ip "${pi_ip}" \
    --panel-manifest "${panel_manifest}" \
    --dirt-manifest "${dirt_manifest}" \
    "${monitor_args[@]}"
