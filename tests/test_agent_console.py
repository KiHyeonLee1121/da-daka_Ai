import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY = Path(__file__).resolve().parents[1]
CONSOLE_PATH = REPOSITORY / "tools" / "dadaka_agent_console.py"
SPEC = importlib.util.spec_from_file_location("dadaka_agent_console", CONSOLE_PATH)
assert SPEC and SPEC.loader
CONSOLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONSOLE)


def test_settings_require_address_only_for_gpu(tmp_path):
    pi = CONSOLE.normalize_settings(
        {"role": "pi", "project_dir": str(tmp_path), "hub_address": ""}
    )
    assert pi["hub_address"] == ""
    gpu = CONSOLE.normalize_settings(
        {
            "role": "gpu",
            "project_dir": str(tmp_path),
            "hub_address": "172.20.10.5",
        }
    )
    assert gpu["hub_address"] == "172.20.10.5"
    with pytest.raises(CONSOLE.ConsoleError):
        CONSOLE.normalize_settings(
            {"role": "gpu", "project_dir": str(tmp_path), "hub_address": ""}
        )


def test_gpu_address_is_applied_immediately_to_ssh_hub(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(
        CONSOLE,
        "run_command",
        lambda command, **_kwargs: captured.append(command) or "hub ok",
    )
    settings = {
        "role": "gpu",
        "hub_address": "192.168.50.23",
        "ssh_user": "kihyeon",
        "project_dir": str(tmp_path),
    }
    assert CONSOLE.configure_bridge(settings, Path("/opt/dadaka-agent")) == "hub ok"
    assert "kihyeon@192.168.50.23" in captured[0]
    assert captured[0][0] == "/opt/dadaka-agent"


def test_only_requests_are_automatic_and_prompt_keeps_safety_boundaries():
    request = {"id": "m1", "from": "gpu", "kind": "request", "body": "test"}
    assert CONSOLE.is_actionable_message(request)
    assert CONSOLE.is_actionable_message({"id": "legacy", "body": "test"})
    assert not CONSOLE.is_actionable_message({"kind": "result"})
    assert not CONSOLE.is_actionable_message({"kind": "note"})
    prompt = CONSOLE.build_codex_prompt(request, "pi")
    assert "workspace" in prompt
    assert "Do not push" in prompt
    assert "flight, MAVROS, PX4" in prompt
    assert '"id": "m1"' in prompt


def test_worker_replies_then_acknowledges_request(tmp_path, monkeypatch):
    project = tmp_path / "repo"
    project.mkdir()
    (project / ".git").mkdir()
    settings = CONSOLE.normalize_settings(
        {"role": "pi", "project_dir": str(project), "hub_address": ""}
    )
    events = []
    worker = CONSOLE.AutomaticAgentWorker(
        settings,
        events.append,
        bridge=Path("/fake/bridge"),
        codex=Path("/fake/codex"),
        state_dir=tmp_path / "state",
    )
    calls = []

    def fake_bridge(arguments, input_text=None):
        calls.append((arguments, input_text))
        return "ok"

    monkeypatch.setattr(worker, "bridge_command", fake_bridge)
    monkeypatch.setattr(
        worker,
        "run_codex",
        lambda _message: ("complete", "테스트 통과", tmp_path / "codex.log"),
    )
    message = {
        "id": "request-1",
        "from": "gpu",
        "to": "pi",
        "kind": "request",
        "task": "unit-test",
        "body": "run tests",
    }
    worker.process_message(message)
    assert calls[0][0][:3] == ["send", "gpu", "--kind"]
    assert "result" in calls[0][0]
    assert "--reply-to" in calls[0][0]
    assert calls[0][1] == "테스트 통과"
    assert calls[1][0] == ["read", "request-1", "--ack"]
    processed = json.loads((tmp_path / "state" / "processed.json").read_text())
    assert processed == ["request-1"]


def test_desktop_entry_uses_absolute_executable():
    entry = CONSOLE.desktop_entry(Path("/home/test/.local/bin/dadaka-agent-console"))
    assert "Type=Application" in entry
    assert "Terminal=false" in entry
    assert "Exec=/home/test/.local/bin/dadaka-agent-console" in entry


def test_automatic_worker_end_to_end_with_fake_codex(tmp_path, monkeypatch):
    bridge = REPOSITORY / "tools" / "dadaka_agent_bridge.py"
    bus = tmp_path / "bus"
    pi_config = tmp_path / "pi.json"
    gpu_config = tmp_path / "gpu.json"
    project = tmp_path / "repo"
    project.mkdir()
    (project / ".git").mkdir()
    fake_codex = tmp_path / "fake-codex"
    fake_codex.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys

arguments = sys.argv[1:]
output = pathlib.Path(arguments[arguments.index('--output-last-message') + 1])
prompt = sys.stdin.read()
assert 'Do not push' in prompt
output.write_text('가짜 자동 Codex 작업 완료', encoding='utf-8')
print('fake codex completed')
""",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)

    def bridge_cli(config, *arguments, input_text=None):
        environment = os.environ.copy()
        environment["DADAKA_AGENT_CONFIG"] = str(config)
        environment["DADAKA_AGENT_BUS_DIR"] = str(bus)
        completed = subprocess.run(
            [sys.executable, str(bridge), *arguments],
            cwd=REPOSITORY,
            env=environment,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        return completed.stdout

    bridge_cli(pi_config, "init", "--name", "pi", "--hub", "local")
    bridge_cli(gpu_config, "init", "--name", "gpu", "--hub", "local")
    sent = bridge_cli(
        gpu_config,
        "send",
        "pi",
        "--kind",
        "request",
        "--task",
        "fake-automatic-test",
        "--body-file",
        "-",
        input_text="안전한 단위시험을 실행하세요.",
    )
    message_id = sent.split()[1]
    monkeypatch.setenv("DADAKA_AGENT_CONFIG", str(pi_config))
    monkeypatch.setenv("DADAKA_AGENT_BUS_DIR", str(bus))
    settings = CONSOLE.normalize_settings(
        {"role": "pi", "project_dir": str(project), "hub_address": ""}
    )
    worker = CONSOLE.AutomaticAgentWorker(
        settings,
        lambda _text: None,
        bridge=bridge,
        codex=fake_codex,
        state_dir=tmp_path / "state",
    )
    messages = json.loads(worker.bridge_command(["inbox", "--json"]))
    worker.process_batch(messages)
    assert json.loads(worker.bridge_command(["inbox", "--json"])) == []

    results = json.loads(bridge_cli(gpu_config, "inbox", "--json"))
    assert len(results) == 1
    assert results[0]["kind"] == "result"
    assert results[0]["reply_to"] == message_id
    assert results[0]["status"] == "complete"
    assert results[0]["body"] == "가짜 자동 Codex 작업 완료"
