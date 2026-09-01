"""Generate machine-readable and beginner-friendly training readiness reports."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from .environment import gpu_environment_report
from .release import (
    DEFAULT_DATASET_FINGERPRINT,
    DEFAULT_DATASET_VERSION,
    DatasetReleaseError,
    verify_dataset_release,
)


def build_readiness_report(
    *,
    dataset_root: str | Path | None = None,
    verification_mode: str = "metadata",
    code_only: bool = False,
    expected_version: str = DEFAULT_DATASET_VERSION,
    expected_fingerprint: str = DEFAULT_DATASET_FINGERPRINT,
) -> dict[str, Any]:
    """Inspect code, optional dataset release and local GPU without training."""
    repo_root = Path(__file__).resolve().parents[2]
    training_root = repo_root / "training"
    code_checks = _code_checks(repo_root, training_root)
    code_ready = all(item["passed"] for item in code_checks)
    dataset = _dataset_status(
        dataset_root,
        verification_mode=verification_mode,
        expected_version=expected_version,
        expected_fingerprint=expected_fingerprint,
        code_only=code_only,
    )
    gpu = _gpu_status(code_only=code_only)

    if not code_ready:
        overall = "BLOCKED_CODE"
        headline = "코드 준비에 문제가 있어 수정이 필요합니다."
    elif code_only:
        overall = "CODE_PREPARED"
        headline = "데이터와 GPU 없이 가능한 코드 준비 검사를 통과했습니다."
    elif dataset["status"] != "VERIFIED":
        overall = "WAITING_FOR_DATA"
        headline = "코드는 준비됐지만 dataset upload/검증 완료를 기다리고 있습니다."
    elif gpu["status"] != "GPU_READY":
        overall = "WAITING_FOR_GPU"
        headline = "Dataset은 준비됐지만 CUDA GPU runtime이 필요합니다."
    else:
        overall = "READY_FOR_TRAINING"
        headline = "Dataset과 CUDA GPU 검사를 통과해 학습을 시작할 수 있습니다."

    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "overall_status": overall,
        "headline": headline,
        "training_started": False,
        "code": {
            "status": "READY" if code_ready else "ERROR",
            "checks": code_checks,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "opencv": cv2.__version__,
            "pyyaml": getattr(yaml, "__version__", "unknown"),
        },
        "dataset": dataset,
        "gpu": gpu,
        "expected_release": {
            "dataset_version": expected_version,
            "dataset_fingerprint": expected_fingerprint,
        },
    }


def write_readiness_report(report: dict[str, Any], output_dir: str | Path) -> dict:
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "training_readiness.json"
    markdown_path = output / "training_readiness.md"
    _atomic_write(
        json_path,
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )
    _atomic_write(markdown_path, render_markdown(report))
    return {"json": str(json_path), "markdown": str(markdown_path)}


def render_markdown(report: dict[str, Any]) -> str:
    overall = report["overall_status"]
    overall_icon = {
        "READY_FOR_TRAINING": "🟢",
        "CODE_PREPARED": "🟢",
        "WAITING_FOR_DATA": "🟡",
        "WAITING_FOR_GPU": "🟡",
        "BLOCKED_CODE": "🔴",
    }.get(overall, "🔴")
    code_icon = "🟢" if report["code"]["status"] == "READY" else "🔴"
    dataset_status = report["dataset"]["status"]
    dataset_icon = "🟢" if dataset_status == "VERIFIED" else "🟡"
    gpu_status = report["gpu"]["status"]
    gpu_icon = "🟢" if gpu_status == "GPU_READY" else "🟡"
    lines = [
        "# DA-DAKA 학습 준비 상태",
        "",
        f"> {overall_icon} **{overall}** — {report['headline']}",
        "",
        "이 보고서는 검사만 수행합니다. 실제 학습이나 dataset 전처리는 실행하지 않았습니다.",
        "",
        "## 한눈에 보기",
        "",
        "| 단계 | 상태 | 의미 |",
        "|---|---|---|",
        f"| 코드·Colab 준비 | {code_icon} {report['code']['status']} | notebook, config, entrypoint와 경로 계약 |",
        f"| Dataset release | {dataset_icon} {dataset_status} | upload와 release 무결성 |",
        f"| 학습 GPU | {gpu_icon} {gpu_status} | CUDA allocation 가능 여부 |",
        f"| 최종 판정 | {overall_icon} {overall} | 세 단계가 모두 준비돼야 학습 시작 |",
        "",
        "## Dataset identity",
        "",
        "```text",
        f"dataset_version: {report['expected_release']['dataset_version']}",
        f"dataset_fingerprint: {report['expected_release']['dataset_fingerprint']}",
        "```",
        "",
        "## 다음 행동",
        "",
    ]
    if overall == "READY_FOR_TRAINING":
        lines.extend(
            [
                "1. loader smoke test 결과를 보존합니다.",
                "2. Panel baseline을 시작합니다.",
                "3. Dirt baseline을 시작합니다.",
                "4. checkpoint와 metadata가 Drive results folder에 저장되는지 확인합니다.",
            ]
        )
    elif overall == "WAITING_FOR_DATA":
        lines.extend(
            [
                "1. Drive upload가 끝날 때까지 학습하지 않습니다.",
                "2. 같은 release를 다시 completeness/fingerprint 검사합니다.",
                "3. 누락이 0이면 `/content`로 staging하고 full verification을 실행합니다.",
            ]
        )
    elif overall == "WAITING_FOR_GPU":
        lines.extend(
            [
                "1. Colab에서 GPU runtime을 선택합니다.",
                "2. GPU doctor를 다시 실행합니다.",
                "3. CUDA allocation 성공 뒤에만 학습합니다.",
            ]
        )
    elif overall == "CODE_PREPARED":
        lines.extend(
            [
                "1. 이 결과는 데이터 없는 코드 준비 검사 통과를 뜻합니다.",
                "2. Drive upload 완료 뒤 dataset root를 지정해 전체 보고서를 다시 만듭니다.",
                "3. 실제 학습은 dataset과 CUDA GPU가 모두 준비된 뒤 시작합니다.",
            ]
        )
    else:
        lines.append("1. 아래 실패한 코드 검사를 먼저 수정합니다.")

    lines.extend(["", "## 코드 검사", ""])
    for check in report["code"]["checks"]:
        icon = "🟢" if check["passed"] else "🔴"
        lines.append(f"- {icon} `{check['name']}`: {check['detail']}")
    if report["dataset"].get("detail"):
        lines.extend(
            ["", "## Dataset 상세", "", f"- {report['dataset']['detail']}"]
        )
    if report["gpu"].get("detail"):
        lines.extend(["", "## GPU 상세", "", f"- {report['gpu']['detail']}"])
    lines.extend(
        [
            "",
            "## 생성 정보",
            "",
            f"- UTC: `{report['generated_at_utc']}`",
            f"- Python: `{report['code']['python']}`",
            f"- Platform: `{report['code']['platform']}`",
            "",
        ]
    )
    return "\n".join(lines)


def _code_checks(repo_root: Path, training_root: Path) -> list[dict[str, Any]]:
    required = (
        training_root / "colab/da_daka_training.ipynb",
        training_root / "configs/dataset_release.yaml",
        training_root / "configs/panel_detector.yaml",
        training_root / "configs/dirt_segmenter.yaml",
        training_root / "requirements-colab.txt",
        training_root / "da_daka_training/release.py",
        training_root / "da_daka_training/loader_smoke.py",
        training_root / "da_daka_training/train_panel.py",
        training_root / "da_daka_training/train_dirt.py",
    )
    missing = [str(path.relative_to(repo_root)) for path in required if not path.is_file()]
    checks: list[dict[str, Any]] = [
        {
            "name": "required_training_files",
            "passed": not missing,
            "detail": "필수 파일 존재" if not missing else f"누락: {missing}",
        }
    ]
    try:
        notebook = json.loads(required[0].read_text(encoding="utf-8"))
        notebook_ok = notebook.get("nbformat") == 4 and bool(notebook.get("cells"))
        notebook_detail = f"nbformat={notebook.get('nbformat')}, cells={len(notebook.get('cells', []))}"
    except (OSError, json.JSONDecodeError) as exc:
        notebook_ok = False
        notebook_detail = str(exc)
    checks.append(
        {"name": "colab_notebook_json", "passed": notebook_ok, "detail": notebook_detail}
    )

    configs_ok = True
    config_detail = []
    for path in required[1:4]:
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
            if (
                path.name in {"panel_detector.yaml", "dirt_segmenter.yaml"}
                and value.get("dataset_root") is not None
            ):
                raise ValueError("dataset_root must be null/injected")
            config_detail.append(path.name)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            configs_ok = False
            config_detail.append(f"{path.name}: {exc}")
    checks.append(
        {
            "name": "training_configs",
            "passed": configs_ok,
            "detail": ", ".join(config_detail),
        }
    )

    absolute_dataset_hits = []
    windows_user_path = re.compile(r"[A-Za-z]:\\\\Users\\\\")
    for path in required[:5]:
        try:
            if windows_user_path.search(path.read_text(encoding="utf-8")):
                absolute_dataset_hits.append(str(path.relative_to(repo_root)))
        except (OSError, UnicodeDecodeError):
            continue
    checks.append(
        {
            "name": "no_windows_user_path_in_training_assets",
            "passed": not absolute_dataset_hits,
            "detail": (
                "Windows 사용자 절대경로 없음"
                if not absolute_dataset_hits
                else f"발견: {absolute_dataset_hits}"
            ),
        }
    )
    return checks


def _dataset_status(
    dataset_root: str | Path | None,
    *,
    verification_mode: str,
    expected_version: str,
    expected_fingerprint: str,
    code_only: bool,
) -> dict[str, Any]:
    if code_only:
        return {"status": "NOT_CHECKED", "detail": "code-only 검사에서는 dataset을 읽지 않음"}
    if dataset_root is None:
        return {"status": "NOT_PROVIDED", "detail": "dataset root가 아직 지정되지 않음"}
    root = Path(dataset_root).expanduser().resolve()
    try:
        verified = verify_dataset_release(
            root,
            expected_version=expected_version,
            expected_fingerprint=expected_fingerprint,
            mode=verification_mode,
        )
    except DatasetReleaseError as exc:
        return {"status": "INCOMPLETE_OR_WRONG_RELEASE", "detail": str(exc), "root": str(root)}
    return {"status": "VERIFIED", "detail": f"{verification_mode} verification 통과", "root": str(root), "report": verified}


def _gpu_status(*, code_only: bool) -> dict[str, Any]:
    if code_only:
        require_cuda = False
    else:
        require_cuda = False
    try:
        report = gpu_environment_report(require_cuda=require_cuda)
    except RuntimeError as exc:
        return {"status": "UNAVAILABLE", "detail": str(exc)}
    status = str(report.get("status"))
    detail = "CUDA allocation 성공" if status == "GPU_READY" else "CUDA GPU가 없어 학습 대기"
    return {"status": status, "detail": detail, "report": report}


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write an intuitive DA-DAKA training readiness report without training"
    )
    parser.add_argument("--dataset-root")
    parser.add_argument("--mode", choices=("metadata", "full"), default="metadata")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--code-only", action="store_true")
    parser.add_argument("--fail-if-not-ready", action="store_true")
    parser.add_argument(
        "--expected-version",
        default=os.environ.get("DA_DAKA_DATASET_VERSION", DEFAULT_DATASET_VERSION),
    )
    parser.add_argument(
        "--expected-fingerprint",
        default=os.environ.get("DA_DAKA_DATASET_FINGERPRINT", DEFAULT_DATASET_FINGERPRINT),
    )
    args = parser.parse_args()
    report = build_readiness_report(
        dataset_root=args.dataset_root,
        verification_mode=args.mode,
        code_only=args.code_only,
        expected_version=args.expected_version,
        expected_fingerprint=args.expected_fingerprint,
    )
    paths = write_readiness_report(report, args.output_dir)
    print(json.dumps({"report": report, "outputs": paths}, indent=2, ensure_ascii=False))
    ready_status = "CODE_PREPARED" if args.code_only else "READY_FOR_TRAINING"
    if args.fail_if_not_ready and report["overall_status"] != ready_status:
        parser.exit(2, f"TRAINING NOT READY: {report['overall_status']}\n")


if __name__ == "__main__":
    main()
