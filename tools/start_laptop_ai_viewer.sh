#!/usr/bin/env bash
set -euo pipefail

repository="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv="${DA_DAKA_VENV:-${repository}/.venv}"
config="${DA_DAKA_CONFIG:-${repository}/laptop_ai/config/laptop_ai.yaml}"
pi_ip="${PI_IP:-}"
dirt_manifest="${DA_DAKA_DIRT_MANIFEST:-${repository}/models/dirt_segmentation_v1/model.json}"
panel_manifest="${DA_DAKA_PANEL_MANIFEST:-${repository}/models/panel_detection_v1/model.json}"
install=false
fullscreen=false
artifact_test=false

usage() {
    cat <<'EOF'
Usage: tools/start_laptop_ai_viewer.sh --pi-ip <PI_IP> [options]

Options:
  --pi-ip ADDRESS       Raspberry Pi field-network address (required)
  --dirt-manifest PATH  trained dirt model bundle manifest
  --panel-manifest PATH trained panel detector bundle manifest
  --config PATH         laptop AI YAML configuration
  --fullscreen          start the monitor in fullscreen mode
  --install             explicitly create/install into the selected venv
  --skip-install        deprecated safe no-op; reuse the existing venv
  --artifact-test       explicitly allow test-only/unapproved bundles
  -h, --help            show this help

By default the script never upgrades or installs packages. It verifies the
existing venv, both manifests, the NVIDIA CUDA provider, and then starts the
integrated monitor. --artifact-test is never production approval.
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
            install=false
            shift
            ;;
        --install)
            install=true
            shift
            ;;
        --artifact-test)
            artifact_test=true
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

if [[ ! -x "${venv}/bin/python" && "${install}" == false ]]; then
    echo "ERROR: existing Python environment not found: ${venv}" >&2
    echo "Use DA_DAKA_VENV=<known-good-venv> or explicitly pass --install." >&2
    exit 2
fi
if [[ ! -x "${venv}/bin/python" && "${install}" == true ]]; then
    command -v python3 >/dev/null || {
        echo "ERROR: python3 is not installed." >&2
        exit 2
    }
    echo "Creating Python environment: ${venv}"
    python3 -m venv "${venv}"
fi

if [[ "${install}" == true ]]; then
    "${venv}/bin/python" -m pip install -e "${repository}/laptop_ai"
fi

export PYTHONPATH="${repository}/laptop_ai${PYTHONPATH:+:${PYTHONPATH}}"

runtime_mode="$("${venv}/bin/python" - "${config}" <<'PY'
import sys, yaml
with open(sys.argv[1], encoding='utf-8') as stream:
    config = yaml.safe_load(stream)
print(config.get('runtime', {}).get('mode', 'production_onnx'))
PY
)"
if [[ "${artifact_test}" == false && "${runtime_mode}" != "production_onnx" ]]; then
    echo "ERROR: production launch requires runtime.mode=production_onnx." >&2
    echo "Use --artifact-test only for explicit no-flight/no-spray testing." >&2
    exit 2
fi

echo "Project: ${repository}"
echo "Python environment: ${venv}"
echo "Laptop IP(s): $(hostname -I)"
echo "Configured Pi override: ${pi_ip}"
echo "Runtime mode: $([[ ${artifact_test} == true ]] && echo artifact_test || echo production_onnx)"

"${venv}/bin/python" -m laptop_ai.nvidia_check

verify_arguments=()
if [[ "${artifact_test}" == true ]]; then
    verify_arguments+=(--allow-test-only)
else
    verify_arguments+=(--require-deployment-approved)
fi
"${venv}/bin/python" -m laptop_ai.verify_pipeline \
    --panel-manifest "${panel_manifest}" \
    --dirt-manifest "${dirt_manifest}" \
    "${verify_arguments[@]}"

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
if [[ "${artifact_test}" == true ]]; then
    arguments+=(--artifact-test)
fi

echo "Starting DA-DAKA monitor. Waiting for Pi camera on UDP 5600."
echo "Keys: Q/ESC quit, S screenshot, F fullscreen"
cd "${repository}"
exec "${venv}/bin/python" "${arguments[@]}"
