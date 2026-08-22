#!/bin/bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DA_DAKA_PROJECT_ROOT="$project_root"
export DA_DAKA_OPERATOR_SOCKET="${DA_DAKA_OPERATOR_SOCKET:-$project_root/ros2_ws/run/operator_gateway.sock}"
export DA_DAKA_COMPOSE_FILE="${DA_DAKA_COMPOSE_FILE:-$project_root/deploy/pi-compose.yaml}"

cd "$project_root"
exec python3 -m operator_app "$@"
