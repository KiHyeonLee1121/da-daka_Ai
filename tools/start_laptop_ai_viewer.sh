#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv="${DA_DAKA_VENV:-${repository}/.venv}"
config="${DA_DAKA_CONFIG:-${repository}/laptop_ai/config/laptop_ai.yaml}"
pi_ip="${PI_IP:-}"
dirt_manifest="${DA_DAKA_DIRT_MANIFEST:-${repository}/models/dirt_segmentation_v1/model.json}"
panel_manifest="${DA_DAKA_PANEL_MANIFEST:-${repository}/models/panel_detection_v1/model.json}"
skip_install=false
fullscreen=false

usage() {
    cat <<'EOF'
Usage: tools/start_laptop_ai_viewer.sh --pi-ip <PI_IP> [options]

Options:
  --pi-ip ADDRESS       Raspberry Pi field-network address (required)
  --dirt-manifest PATH  trained dirt model bundle manifest
  --panel-manifest PATH trained panel detector bundle manifest
  --config PATH         laptop AI YAML configuration
  --fullscreen          start the monitor in fullscreen mode
  --skip-install        reuse an already prepared virtual environment
  -h, --help            show this help

The script creates .venv on first run, installs laptop_ai, verifies the
NVIDIA CUDA provider, and starts the integrated camera/AI monitor.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --pi-ip)
            pi_ip="${2:?--pi-ip requires an address}"
            shift 2
            ;;
        --dirt-manifest)
            dirt_manifest="${2:?--dirt-manifest requires a path}"
            shift 2
            ;;
        --panel-manifest)
            panel_manifest="${2:?--panel-manifest requires a path}"
            shift 2
            ;;
        --config)
            config="${2:?--config requires a path}"
            shift 2
            ;;
        --fullscreen)
            fullscreen=true
            shift
            ;;
        --skip-install)
            skip_install=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ -z "${pi_ip}" ]]; then
    echo "ERROR: provide the current Pi address with --pi-ip." >&2
    exit 2
fi
if [[ ! -f "${config}" ]]; then
    echo "ERROR: configuration not found: ${config}" >&2
    exit 2
fi
if [[ ! -f "${dirt_manifest}" ]]; then
    echo "ERROR: dirt model manifest not found: ${dirt_manifest}" >&2
    exit 2
fi
if [[ ! -f "${panel_manifest}" ]]; then
    echo "ERROR: panel model manifest not found: ${panel_manifest}" >&2
    exit 2
fi

if [[ ! -x "${venv}/bin/python" ]]; then
    command -v python3 >/dev/null || {
        echo "ERROR: python3 is not installed." >&2
        exit 2
    }
    echo "Creating Python environment: ${venv}"
    python3 -m venv "${venv}"
fi

if [[ "${skip_install}" == false ]]; then
    "${venv}/bin/python" -m pip install --upgrade pip
    "${venv}/bin/python" -m pip install -e "${repository}/laptop_ai"
fi

"${venv}/bin/python" -m laptop_ai.nvidia_check

arguments=(
    -m laptop_ai.viewer_app
    --config "${config}"
    --pi-ip "${pi_ip}"
    --dirt-manifest "${dirt_manifest}"
    --panel-manifest "${panel_manifest}"
)
if [[ "${fullscreen}" == true ]]; then
    arguments+=(--fullscreen)
fi

echo "Starting DA-DAKA monitor. Waiting for Pi camera on UDP 5600."
echo "Keys: Q/ESC quit, S screenshot, F fullscreen"
cd "${repository}"
exec "${venv}/bin/python" "${arguments[@]}"
