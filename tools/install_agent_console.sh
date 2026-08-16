#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 3 ]]; then
    echo "Usage:" >&2
    echo "  $0 pi [project-dir]" >&2
    echo "  $0 gpu <pi-address> [project-dir]" >&2
    exit 2
fi

role=$1
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
install_dir="${HOME}/.local/bin"
bridge_source="${script_dir}/dadaka_agent_bridge.py"
console_source="${script_dir}/dadaka_agent_console.py"
bridge="${install_dir}/dadaka-agent"
console="${install_dir}/dadaka-agent-console"
ssh_user="${DADAKA_PI_USER:-kihyeon}"

case "${role}" in
    pi)
        hub_address=""
        project_dir="${2:-$(pwd)}"
        bridge_hub="local"
        ;;
    gpu)
        if [[ $# -lt 2 ]]; then
            echo "GPU 설치에는 Pi 주소가 필요합니다." >&2
            exit 2
        fi
        hub_address=$2
        project_dir="${3:-${HOME}/da-daka_Ai}"
        bridge_hub="${ssh_user}@${hub_address}"
        ;;
    *)
        echo "Role must be pi or gpu." >&2
        exit 2
        ;;
esac

python3 -c 'import tkinter; print("Tk", tkinter.TkVersion)'
command -v codex >/dev/null
install -d -m 0755 "${install_dir}"
install -m 0755 "${bridge_source}" "${bridge}"
install -m 0755 "${console_source}" "${console}"

"${bridge}" init \
    --name "${role}" \
    --hub "${bridge_hub}" \
    --remote-command "/home/${ssh_user}/.local/bin/dadaka-agent"

"${console}" \
    --configure-role "${role}" \
    --hub-address "${hub_address}" \
    --ssh-user "${ssh_user}" \
    --project-dir "${project_dir}" \
    --auto-start true
"${console}" --install-desktop

if [[ -n ${DISPLAY:-} ]]; then
    "${console}" --smoke-test
fi

echo
echo "Installed ${console}"
echo "Desktop shortcut: ${HOME}/Desktop/DA-DAKA-Agent-Console.desktop"
