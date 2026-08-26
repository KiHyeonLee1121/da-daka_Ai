#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv="${DA_DAKA_VENV:-${repository}/.venv}"
desktop_directory="${DA_DAKA_DESKTOP_DIR:-}"

if [[ -z "${desktop_directory}" ]] && command -v xdg-user-dir >/dev/null 2>&1; then
    desktop_directory="$(xdg-user-dir DESKTOP)"
fi
if [[ -z "${desktop_directory}" ]]; then
    user_home="$(getent passwd "$(id -u)" | cut -d: -f6)"
    desktop_directory="${user_home}/Desktop"
fi

for required in \
    "${repository}/desktop/da-daka-gpu-live-monitor.desktop.in" \
    "${repository}/desktop/da-daka-find-pi.desktop.in" \
    "${repository}/tools/start_live_ai_monitor_desktop.sh" \
    "${repository}/tools/find_raspberry_pi_desktop.sh"; do
    if [[ ! -f "${required}" ]]; then
        echo "ERROR: required desktop application file is missing: ${required}" >&2
        exit 2
    fi
done

mkdir -p "${desktop_directory}"
temporary_directory="$(mktemp -d)"
cleanup() {
    rm -rf -- "${temporary_directory}"
}
trap cleanup EXIT

escape_sed_replacement() {
    printf '%s' "$1" | sed 's/[\\&|]/\\&/g'
}

render_launcher() {
    local template="$1"
    local destination="$2"
    local live_launcher pi_finder known_venv
    live_launcher="$(escape_sed_replacement "${repository}/tools/start_live_ai_monitor_desktop.sh")"
    pi_finder="$(escape_sed_replacement "${repository}/tools/find_raspberry_pi_desktop.sh")"
    known_venv="$(escape_sed_replacement "${venv}")"
    sed \
        -e "s|@LIVE_LAUNCHER@|${live_launcher}|g" \
        -e "s|@PI_FINDER@|${pi_finder}|g" \
        -e "s|@VENV@|${known_venv}|g" \
        "${template}" > "${temporary_directory}/${destination}"
    install -m 0755 \
        "${temporary_directory}/${destination}" \
        "${desktop_directory}/${destination}"
    if command -v gio >/dev/null 2>&1; then
        gio set "${desktop_directory}/${destination}" \
            metadata::trusted true 2>/dev/null || true
    fi
}

render_launcher \
    "${repository}/desktop/da-daka-gpu-live-monitor.desktop.in" \
    'DA-DAKA_GPU_실시간_AI_모니터.desktop'
render_launcher \
    "${repository}/desktop/da-daka-find-pi.desktop.in" \
    'DA-DAKA_같은네트워크_Pi_IP찾기.desktop'

echo "설치 완료: ${desktop_directory}/DA-DAKA_GPU_실시간_AI_모니터.desktop"
echo "설치 완료: ${desktop_directory}/DA-DAKA_같은네트워크_Pi_IP찾기.desktop"
