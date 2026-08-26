#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "${repository}/tools/find_raspberry_pi.py"
echo
read -r -p 'Enter를 누르면 닫습니다.' || true
