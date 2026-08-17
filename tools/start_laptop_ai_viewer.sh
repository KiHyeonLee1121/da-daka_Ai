#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv="${DA_DAKA_VENV:-${repository}/.venv}"
config="${DA_DAKA_CONFIG:-${repository}/laptop_ai/config/laptop_ai.yaml}"
pi_ip="${PI_IP:-}"
model="${DA_DAKA_MODEL:-${repository}/models/dirt_segmentation.onnx}"
skip_install=false
fullscreen=false

usage() {
    cat <<'EOF'
Usage: tools/start_laptop_ai_viewer.sh --pi-ip <PI_IP> [options]

Options:
  --pi-ip ADDRESS       Raspberry Pi field-network address (required)
  --model PATH          trained dirt segmentation ONNX model
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
        --model)
            model="${2:?--model requires a path}"
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
if [[ ! -f "${model}" ]]; then
    echo "ERROR: trained ONNX model not found: ${model}" >&2
    echo "Place dirt_segmentation.onnx in ${repository}/models or use --model." >&2
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
    --model "${model}"
)
if [[ "${fullscreen}" == true ]]; then
    arguments+=(--fullscreen)
fi

echo "Starting DA-DAKA monitor. Waiting for Pi camera on UDP 5600."
echo "Keys: Q/ESC quit, S screenshot, F fullscreen"
cd "${repository}"
exec "${venv}/bin/python" "${arguments[@]}"

