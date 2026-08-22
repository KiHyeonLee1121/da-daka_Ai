#!/bin/bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
desktop_source="$project_root/deploy/da-daka-operator.desktop"
application_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

if ! python3 -c 'import PyQt5' >/dev/null 2>&1; then
    echo "PyQt5 is missing. Install it first: sudo apt install python3-pyqt5" >&2
    exit 1
fi

mkdir -p "$application_dir"
install -m 0644 "$desktop_source" "$application_dir/da-daka-operator.desktop"
chmod +x "$project_root/tools/start_pi_operator_app.sh"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$application_dir" >/dev/null 2>&1 || true
fi

echo "Installed DA-DAKA operator application menu entry."
echo "Run: $project_root/tools/start_pi_operator_app.sh"
