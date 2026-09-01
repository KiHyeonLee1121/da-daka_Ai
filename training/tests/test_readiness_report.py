import json

from da_daka_training.readiness import (
    build_readiness_report,
    render_markdown,
    write_readiness_report,
)


def test_code_only_readiness_is_green_and_writes_both_formats(tmp_path):
    report = build_readiness_report(code_only=True)
    assert report["overall_status"] == "CODE_PREPARED"
    assert report["training_started"] is False
    assert report["code"]["status"] == "READY"
    assert report["dataset"]["status"] == "NOT_CHECKED"

    outputs = write_readiness_report(report, tmp_path)
    parsed = json.loads(
        (tmp_path / "training_readiness.json").read_text(encoding="utf-8")
    )
    markdown = (tmp_path / "training_readiness.md").read_text(encoding="utf-8")
    assert parsed["overall_status"] == "CODE_PREPARED"
    assert "한눈에 보기" in markdown
    assert outputs["json"].endswith("training_readiness.json")


def test_missing_dataset_is_reported_without_starting_training(tmp_path):
    report = build_readiness_report(dataset_root=tmp_path / "missing")
    assert report["overall_status"] == "WAITING_FOR_DATA"
    assert report["dataset"]["status"] == "INCOMPLETE_OR_WRONG_RELEASE"
    assert report["training_started"] is False
    assert "Dataset release" in render_markdown(report)
