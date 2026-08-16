import json
import os
from pathlib import Path
import stat
import subprocess
import sys


REPOSITORY = Path(__file__).resolve().parents[1]
BRIDGE = REPOSITORY / "tools" / "dadaka_agent_bridge.py"


def run_bridge(config, bus, *arguments, input_text=None, expected=0):
    environment = os.environ.copy()
    environment["DADAKA_AGENT_CONFIG"] = str(config)
    environment["DADAKA_AGENT_BUS_DIR"] = str(bus)
    completed = subprocess.run(
        [sys.executable, str(BRIDGE), *arguments],
        cwd=REPOSITORY,
        env=environment,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    assert completed.returncode == expected, completed.stderr
    return completed


def test_local_send_receive_reply_round_trip(tmp_path):
    bus = tmp_path / "bus"
    pi_config = tmp_path / "pi.json"
    gpu_config = tmp_path / "gpu.json"

    run_bridge(pi_config, bus, "init", "--name", "pi", "--hub", "local")
    run_bridge(gpu_config, bus, "init", "--name", "gpu", "--hub", "local")
    assert stat.S_IMODE((bus / "unread").stat().st_mode) == 0o700
    assert stat.S_IMODE((bus / "read").stat().st_mode) == 0o700

    sent = run_bridge(
        pi_config,
        bus,
        "send",
        "gpu",
        "카메라 준비 완료",
        "--task",
        "camera-test",
        "--status",
        "ready",
        "--artifact",
        "docs/edge_gpu_offload_runbook.md",
    )
    message_id = sent.stdout.split()[1]

    inbox = run_bridge(gpu_config, bus, "inbox", "--json")
    messages = json.loads(inbox.stdout)
    assert len(messages) == 1
    assert messages[0]["id"] == message_id
    assert messages[0]["from"] == "pi"
    assert messages[0]["to"] == "gpu"
    assert messages[0]["task"] == "camera-test"
    assert messages[0]["kind"] == "request"
    assert messages[0]["status"] == "ready"
    assert messages[0]["repository"] == "da-daka_Ai"
    assert isinstance(messages[0]["worktree_dirty"], bool)
    assert stat.S_IMODE((bus / "unread").stat().st_mode) == 0o700
    assert stat.S_IMODE((bus / "unread" / "gpu").stat().st_mode) == 0o700
    message_path = bus / "unread" / "gpu" / f"{message_id}.json"
    assert stat.S_IMODE(message_path.stat().st_mode) == 0o600

    received = run_bridge(gpu_config, bus, "receive", "--json")
    assert json.loads(received.stdout)[0]["body"] == "카메라 준비 완료"
    assert json.loads(run_bridge(gpu_config, bus, "inbox", "--json").stdout) == []

    run_bridge(gpu_config, bus, "reply", message_id, "GPU 수신 완료")
    replies = json.loads(run_bridge(pi_config, bus, "receive", "--json").stdout)
    assert replies[0]["from"] == "gpu"
    assert replies[0]["to"] == "pi"
    assert replies[0]["reply_to"] == message_id
    assert replies[0]["kind"] == "result"
    assert replies[0]["body"] == "GPU 수신 완료"

    status = run_bridge(pi_config, bus, "status")
    assert "unread=0" in status.stdout
    assert "read=1" in status.stdout


def test_body_can_be_read_from_stdin(tmp_path):
    bus = tmp_path / "bus"
    config = tmp_path / "pi.json"
    run_bridge(config, bus, "init", "--name", "pi", "--hub", "local")
    run_bridge(config, bus, "send", "gpu", input_text="multiline\nmessage\n")
    message_path = next((bus / "unread" / "gpu").glob("*.json"))
    message = json.loads(message_path.read_text(encoding="utf-8"))
    assert message["body"] == "multiline\nmessage\n"


def test_rejects_path_traversal_identity(tmp_path):
    result = run_bridge(
        tmp_path / "config.json",
        tmp_path / "bus",
        "init",
        "--name",
        "../gpu",
        "--hub",
        "local",
        expected=2,
    )
    assert "agent name" in result.stderr
    assert not (tmp_path / "gpu").exists()


def test_hub_protocol_rejects_oversized_body(tmp_path):
    environment = os.environ.copy()
    environment["DADAKA_AGENT_BUS_DIR"] = str(tmp_path / "bus")
    request = {
        "op": "send",
        "message": {"from": "pi", "to": "gpu", "body": "x" * (64 * 1024 + 1)},
    }
    completed = subprocess.run(
        [sys.executable, str(BRIDGE), "__hub"],
        env=environment,
        input=json.dumps(request),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 2
    assert "exceeds" in completed.stderr
