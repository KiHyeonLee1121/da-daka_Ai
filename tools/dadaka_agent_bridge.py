#!/usr/bin/env python3
"""Small SSH-backed mailbox for the two DA-DAKA Codex terminals."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import uuid


MAX_BODY_BYTES = 64 * 1024
MAX_RPC_BYTES = 128 * 1024
IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
MESSAGE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")
SSH_TARGET_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:@[A-Za-z0-9_.:-]+)?$")
REMOTE_COMMAND_RE = re.compile(r"^[/~A-Za-z0-9_.-]+$")


class BridgeError(RuntimeError):
    """Expected configuration, validation, transport, or mailbox error."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def validate_identity(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTITY_RE.fullmatch(value):
        raise BridgeError(
            f"{label} must match {IDENTITY_RE.pattern!r}; got {value!r}"
        )
    return value


def validate_message_id(value: object) -> str:
    if not isinstance(value, str) or not MESSAGE_ID_RE.fullmatch(value):
        raise BridgeError("invalid message id")
    return value


def config_path(value: str | None = None) -> Path:
    raw = value or os.environ.get(
        "DADAKA_AGENT_CONFIG", "~/.config/dadaka-agent/config.json"
    )
    return Path(raw).expanduser()


def bus_root() -> Path:
    raw = os.environ.get("DADAKA_AGENT_BUS_DIR", "~/.local/share/dadaka-agent")
    return Path(raw).expanduser()


def ensure_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError as exc:
        raise BridgeError(f"cannot secure directory {path}: {exc}") from exc


def atomic_write_json(path: Path, data: object, mode: int = 0o600) -> None:
    ensure_private_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.chmod(mode)
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def read_json_file(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise BridgeError(f"invalid mailbox file: {path.name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeError(f"cannot read mailbox file {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise BridgeError(f"mailbox file {path.name} is not a JSON object")
    return data


def ensure_bus_directories(root: Path) -> None:
    ensure_private_directory(root)
    ensure_private_directory(root / "unread")
    ensure_private_directory(root / "read")


def load_config(path: Path) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BridgeError(
            f"not initialized: run 'dadaka-agent init --name <pi|gpu> "
            f"--hub <local|user@pi-ip>' (config: {path})"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeError(f"cannot read config {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise BridgeError(f"config {path} must contain a JSON object")

    name = os.environ.get("DADAKA_AGENT_NAME", raw.get("name", ""))
    hub = os.environ.get("DADAKA_AGENT_HUB", raw.get("hub", ""))
    remote_command = os.environ.get(
        "DADAKA_AGENT_REMOTE_COMMAND",
        raw.get("remote_command", "/home/kihyeon/.local/bin/dadaka-agent"),
    )
    name = validate_identity(name, "agent name")
    if hub != "local" and (
        not isinstance(hub, str)
        or not SSH_TARGET_RE.fullmatch(hub)
        or hub.startswith("-")
    ):
        raise BridgeError(f"invalid SSH hub target: {hub!r}")
    if not isinstance(remote_command, str) or not REMOTE_COMMAND_RE.fullmatch(
        remote_command
    ):
        raise BridgeError(f"invalid remote command: {remote_command!r}")
    return {"name": name, "hub": hub, "remote_command": remote_command}


def mailbox_directory(root: Path, state: str, recipient: str) -> Path:
    validate_identity(recipient, "recipient")
    if state not in {"unread", "read"}:
        raise BridgeError("invalid mailbox state")
    ensure_bus_directories(root)
    state_directory = root / state
    ensure_private_directory(state_directory)
    directory = state_directory / recipient
    ensure_private_directory(directory)
    return directory


def mailbox_files(root: Path, state: str, recipient: str) -> list[Path]:
    directory = mailbox_directory(root, state, recipient)
    return sorted(
        path
        for path in directory.glob("*.json")
        if path.is_file() and not path.is_symlink()
    )


def validate_optional_text(
    message: dict[str, object], field: str, maximum: int = 512
) -> None:
    value = message.get(field)
    if value is not None and (not isinstance(value, str) or len(value) > maximum):
        raise BridgeError(f"message field {field!r} is invalid")


def normalize_message(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise BridgeError("message must be a JSON object")
    sender = validate_identity(raw.get("from"), "sender")
    recipient = validate_identity(raw.get("to"), "recipient")
    body = raw.get("body")
    if not isinstance(body, str) or not body.strip():
        raise BridgeError("message body must be non-empty text")
    if len(body.encode("utf-8")) > MAX_BODY_BYTES:
        raise BridgeError(f"message body exceeds {MAX_BODY_BYTES} bytes")

    normalized: dict[str, object] = {
        "from": sender,
        "to": recipient,
        "body": body,
    }
    kind = raw.get("kind", "request")
    if kind not in {"request", "result", "note"}:
        raise BridgeError("message kind must be request, result, or note")
    normalized["kind"] = kind
    for field in ("task", "status", "repository", "branch", "commit", "reply_to"):
        if field in raw and raw[field] is not None:
            normalized[field] = raw[field]
            validate_optional_text(normalized, field)
    worktree_dirty = raw.get("worktree_dirty")
    if worktree_dirty is not None:
        if not isinstance(worktree_dirty, bool):
            raise BridgeError("message field 'worktree_dirty' must be true or false")
        normalized["worktree_dirty"] = worktree_dirty
    if "reply_to" in normalized:
        validate_message_id(normalized["reply_to"])

    artifacts = raw.get("artifacts", [])
    if not isinstance(artifacts, list) or len(artifacts) > 32:
        raise BridgeError("artifacts must be a list of at most 32 paths or URLs")
    if any(not isinstance(item, str) or len(item) > 2048 for item in artifacts):
        raise BridgeError("each artifact must be text no longer than 2048 characters")
    normalized["artifacts"] = artifacts
    return normalized


def new_message_id() -> str:
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}-{uuid.uuid4().hex[:10]}"


def hub_send(root: Path, raw: object) -> dict[str, object]:
    message = normalize_message(raw)
    message["id"] = new_message_id()
    message["created_at"] = utc_now()
    destination = mailbox_directory(root, "unread", str(message["to"]))
    atomic_write_json(destination / f"{message['id']}.json", message)
    return {"ok": True, "message": message}


def find_message(
    root: Path, recipient: str, message_id: str
) -> tuple[Path, str, dict[str, object]]:
    validate_identity(recipient, "recipient")
    validate_message_id(message_id)
    for state in ("unread", "read"):
        path = mailbox_directory(root, state, recipient) / f"{message_id}.json"
        if path.exists():
            return path, state, read_json_file(path)
    raise BridgeError(f"message not found for {recipient}: {message_id}")


def mark_read(root: Path, recipient: str, path: Path) -> Path:
    destination = mailbox_directory(root, "read", recipient) / path.name
    if destination.exists():
        raise BridgeError(f"read mailbox already contains {path.name}")
    os.replace(path, destination)
    return destination


def hub_dispatch(root: Path, request: object) -> dict[str, object]:
    if not isinstance(request, dict):
        raise BridgeError("hub request must be a JSON object")
    operation = request.get("op")
    if operation == "ping":
        ensure_bus_directories(root)
        return {
            "ok": True,
            "host": socket.gethostname(),
            "root": str(root),
            "time": utc_now(),
        }
    if operation == "send":
        return hub_send(root, request.get("message"))

    recipient = validate_identity(request.get("recipient"), "recipient")
    if operation in {"inbox", "receive"}:
        paths = mailbox_files(root, "unread", recipient)
        messages = [read_json_file(path) for path in paths]
        if operation == "receive":
            for path in paths:
                mark_read(root, recipient, path)
        return {"ok": True, "messages": messages, "count": len(messages)}
    if operation == "read":
        path, state, message = find_message(
            root, recipient, validate_message_id(request.get("id"))
        )
        if bool(request.get("ack")) and state == "unread":
            mark_read(root, recipient, path)
            state = "read"
        return {"ok": True, "message": message, "state": state}
    if operation == "status":
        unread = len(mailbox_files(root, "unread", recipient))
        read = len(mailbox_files(root, "read", recipient))
        return {"ok": True, "recipient": recipient, "unread": unread, "read": read}
    raise BridgeError(f"unsupported hub operation: {operation!r}")


def remote_hub_request(config: dict[str, str], request: dict[str, object]) -> dict:
    command = [
        "ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "ServerAliveInterval=10",
        "-o",
        "ServerAliveCountMax=2",
        "-o",
        "StrictHostKeyChecking=accept-new",
        config["hub"],
        config["remote_command"],
        "__hub",
    ]
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(request, ensure_ascii=False),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BridgeError(f"SSH hub request failed: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise BridgeError(f"SSH hub returned {completed.returncode}: {detail}")
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise BridgeError("SSH hub returned invalid JSON") from exc
    if not isinstance(response, dict):
        raise BridgeError("SSH hub response must be a JSON object")
    if not response.get("ok", False):
        raise BridgeError(str(response.get("error", "unknown hub error")))
    return response


def hub_request(config: dict[str, str], request: dict[str, object]) -> dict:
    if config["hub"] == "local":
        return hub_dispatch(bus_root(), request)
    return remote_hub_request(config, request)


def git_metadata() -> dict[str, object]:
    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
        return completed.stdout.strip() if completed.returncode == 0 else ""

    try:
        root = git("rev-parse", "--show-toplevel")
        if not root:
            return {}
        origin = git("remote", "get-url", "origin")
        repository = Path(root).name
        if origin:
            repository = origin.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        metadata = {
            "repository": repository,
            "branch": git("branch", "--show-current"),
            "commit": git("rev-parse", "--short=12", "HEAD"),
        }
        result: dict[str, object] = {
            key: value for key, value in metadata.items() if value
        }
        result["worktree_dirty"] = bool(git("status", "--porcelain"))
        return result
    except (OSError, subprocess.TimeoutExpired):
        return {}


def message_body(args: argparse.Namespace) -> str:
    if args.body_file:
        if args.body is not None:
            raise BridgeError("use either BODY or --body-file, not both")
        if args.body_file == "-":
            return sys.stdin.read()
        try:
            return Path(args.body_file).read_text(encoding="utf-8")
        except OSError as exc:
            raise BridgeError(f"cannot read body file {args.body_file}: {exc}") from exc
    if args.body is not None:
        return args.body
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise BridgeError("message body is required as BODY, --body-file, or standard input")


def build_outgoing_message(
    config: dict[str, str], args: argparse.Namespace, recipient: str, body: str
) -> dict[str, object]:
    message: dict[str, object] = {
        "from": config["name"],
        "to": validate_identity(recipient, "recipient"),
        "body": body,
        "kind": getattr(args, "kind", "request"),
        "artifacts": args.artifact or [],
    }
    message.update(git_metadata())
    for field in ("task", "status", "reply_to"):
        value = getattr(args, field, None)
        if value:
            message[field] = value
    return message


def print_message(message: dict[str, object]) -> None:
    print(f"[{message.get('id', '?')}] {message.get('from')} -> {message.get('to')}")
    details = []
    for label in (
        "task",
        "kind",
        "status",
        "repository",
        "branch",
        "commit",
        "worktree_dirty",
        "reply_to",
    ):
        if message.get(label):
            details.append(f"{label}={message[label]}")
    if details:
        print("  " + " | ".join(details))
    print(str(message.get("body", "")))
    artifacts = message.get("artifacts", [])
    if artifacts:
        print("artifacts:")
        for artifact in artifacts:
            print(f"  - {artifact}")


def print_messages(messages: list[dict[str, object]], json_output: bool) -> None:
    if json_output:
        print(json.dumps(messages, ensure_ascii=False, indent=2))
        return
    if not messages:
        print("읽지 않은 메시지가 없습니다.")
        return
    for index, message in enumerate(messages):
        if index:
            print()
        print_message(message)


def add_message_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("body", nargs="?", metavar="BODY")
    parser.add_argument("--body-file", metavar="PATH", help="read body from PATH; '-' means stdin")
    parser.add_argument("--task")
    parser.add_argument("--status")
    parser.add_argument(
        "--kind", choices=("request", "result", "note"), default="request"
    )
    parser.add_argument("--reply-to")
    parser.add_argument("--artifact", action="append", default=[])


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dadaka-agent",
        description="SSH-backed mailbox for the DA-DAKA Pi and GPU Codex terminals",
    )
    parser.add_argument("--config", help="config JSON path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="configure this machine")
    init_parser.add_argument("--name", required=True, help="agent name, normally pi or gpu")
    init_parser.add_argument(
        "--hub", required=True, help="local on the Pi, or user@pi-address on the laptop"
    )
    init_parser.add_argument(
        "--remote-command", default="/home/kihyeon/.local/bin/dadaka-agent"
    )
    init_parser.add_argument("--skip-check", action="store_true")

    subparsers.add_parser("ping", help="check the mailbox hub")
    subparsers.add_parser("status", help="show unread/read counts for this agent")

    send_parser = subparsers.add_parser("send", help="send a message")
    send_parser.add_argument("to", help="recipient agent name")
    add_message_arguments(send_parser)

    inbox_parser = subparsers.add_parser("inbox", help="show unread messages without acknowledging")
    inbox_parser.add_argument("--json", action="store_true")

    receive_parser = subparsers.add_parser(
        "receive", aliases=["recv"], help="show unread messages and mark them read"
    )
    receive_parser.add_argument("--json", action="store_true")

    read_parser = subparsers.add_parser("read", help="read one message by id")
    read_parser.add_argument("id")
    read_parser.add_argument("--ack", action="store_true")
    read_parser.add_argument("--json", action="store_true")

    reply_parser = subparsers.add_parser("reply", help="reply to a received message")
    reply_parser.add_argument("id")
    add_message_arguments(reply_parser)

    subparsers.add_parser("__hub", help=argparse.SUPPRESS)
    return parser


def initialize(args: argparse.Namespace) -> int:
    path = config_path(args.config)
    name = validate_identity(args.name, "agent name")
    hub = args.hub
    if hub != "local" and (
        not SSH_TARGET_RE.fullmatch(hub) or hub.startswith("-")
    ):
        raise BridgeError(f"invalid SSH hub target: {hub!r}")
    if not REMOTE_COMMAND_RE.fullmatch(args.remote_command):
        raise BridgeError(f"invalid remote command: {args.remote_command!r}")
    config = {"name": name, "hub": hub, "remote_command": args.remote_command}
    atomic_write_json(path, config)
    if not args.skip_check:
        response = hub_request(config, {"op": "ping"})
        print(f"hub ok: {response['host']} ({response['root']})")
    print(f"configured {name!r} in {path}")
    return 0


def run_hub_protocol() -> int:
    raw = sys.stdin.buffer.read(MAX_RPC_BYTES + 1)
    if len(raw) > MAX_RPC_BYTES:
        raise BridgeError(f"hub request exceeds {MAX_RPC_BYTES} bytes")
    try:
        request = json.loads(raw.decode("utf-8"))
        response = hub_dispatch(bus_root(), request)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BridgeError(f"invalid hub request JSON: {exc}") from exc
    print(json.dumps(response, ensure_ascii=False))
    return 0


def run_client(args: argparse.Namespace) -> int:
    config = load_config(config_path(args.config))
    if args.command == "ping":
        response = hub_request(config, {"op": "ping"})
        print(f"hub ok: {response['host']} ({response['root']}) at {response['time']}")
        return 0
    if args.command == "status":
        response = hub_request(
            config, {"op": "status", "recipient": config["name"]}
        )
        print(
            f"{config['name']}: unread={response['unread']} read={response['read']}"
        )
        return 0
    if args.command == "send":
        outgoing = build_outgoing_message(config, args, args.to, message_body(args))
        response = hub_request(config, {"op": "send", "message": outgoing})
        message = response["message"]
        print(f"sent {message['id']} to {message['to']}")
        return 0
    if args.command == "inbox":
        response = hub_request(
            config, {"op": "inbox", "recipient": config["name"]}
        )
        print_messages(response["messages"], args.json)
        return 0
    if args.command in {"receive", "recv"}:
        response = hub_request(
            config, {"op": "receive", "recipient": config["name"]}
        )
        print_messages(response["messages"], args.json)
        return 0
    if args.command == "read":
        response = hub_request(
            config,
            {
                "op": "read",
                "recipient": config["name"],
                "id": args.id,
                "ack": args.ack,
            },
        )
        if args.json:
            print(json.dumps(response["message"], ensure_ascii=False, indent=2))
        else:
            print_message(response["message"])
        return 0
    if args.command == "reply":
        original_response = hub_request(
            config,
            {
                "op": "read",
                "recipient": config["name"],
                "id": args.id,
                "ack": False,
            },
        )
        original = original_response["message"]
        args.reply_to = args.id
        args.kind = "result"
        outgoing = build_outgoing_message(
            config, args, str(original["from"]), message_body(args)
        )
        response = hub_request(config, {"op": "send", "message": outgoing})
        hub_request(
            config,
            {
                "op": "read",
                "recipient": config["name"],
                "id": args.id,
                "ack": True,
            },
        )
        message = response["message"]
        print(f"sent reply {message['id']} to {message['to']}")
        return 0
    raise BridgeError(f"unsupported command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "__hub":
            return run_hub_protocol()
        if args.command == "init":
            return initialize(args)
        return run_client(args)
    except BridgeError as exc:
        print(f"dadaka-agent: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
