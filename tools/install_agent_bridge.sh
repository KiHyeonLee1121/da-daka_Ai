#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
    echo "Usage: $0 <agent-name> <local|user@pi-ip> [remote-command]" >&2
    echo "Pi:     $0 pi local" >&2
    echo "Laptop: $0 gpu kihyeon@172.20.10.5" >&2
    exit 2
fi

agent_name=$1
hub=$2
remote_command=${3:-/home/kihyeon/.local/bin/dadaka-agent}
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source_script="${script_dir}/dadaka_agent_bridge.py"
install_dir="${HOME}/.local/bin"
installed_script="${install_dir}/dadaka-agent"

if [[ ! -f ${source_script} ]]; then
    echo "Missing ${source_script}" >&2
    exit 1
fi

install -d -m 0755 "${install_dir}"
install -m 0755 "${source_script}" "${installed_script}"
"${installed_script}" init \
    --name "${agent_name}" \
    --hub "${hub}" \
    --remote-command "${remote_command}"

echo
echo "Installed: ${installed_script}"
echo "Open a new shell or run: export PATH=\"\${HOME}/.local/bin:\${PATH}\""
echo "Test with: dadaka-agent ping"
