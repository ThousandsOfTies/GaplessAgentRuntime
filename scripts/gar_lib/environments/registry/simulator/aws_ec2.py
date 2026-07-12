"""Simulation VM control for `gar sim start/stop/status` over AWS CLI.

旧 Windows PowerShell EC2 helper の Python 移植。WSL2 から AWS CLI を呼び、起動後は public IP を
取得して ``~/.ssh/config`` の対象 Host の ``HostName`` を更新する。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.gar_lib.config import (
    default_ec2_host,
    default_ec2_instance_id,
    default_ec2_region,
    ec2_repo_dir,
    load_config,
)

SSH_CONFIG_PATH = Path.home() / ".ssh" / "config"
COMMAND_LABEL = "gar sim VM"


def _aws_available() -> bool:
    return shutil.which("aws") is not None


def _run_aws(args: list[str], *, region: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["aws", *args, "--region", region],
        check=False,
        capture_output=True,
        text=True,
    )


def ec2_instance_state(instance_id: str, region: str) -> str | None:
    """インスタンスの state 名 (running/stopped/...) を返す。失敗時は None。"""
    result = _run_aws(
        [
            "ec2",
            "describe-instances",
            "--instance-ids",
            instance_id,
            "--query",
            "Reservations[0].Instances[0].State.Name",
            "--output",
            "text",
        ],
        region=region,
    )
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        return None
    state = result.stdout.strip()
    return state or None


def ec2_public_ip(instance_id: str, region: str) -> str | None:
    """インスタンスの public IP を返す。未割り当て/失敗時は None。"""
    result = _run_aws(
        [
            "ec2",
            "describe-instances",
            "--instance-ids",
            instance_id,
            "--query",
            "Reservations[0].Instances[0].PublicIpAddress",
            "--output",
            "text",
        ],
        region=region,
    )
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        return None
    ip = result.stdout.strip()
    if not ip or ip == "None":
        return None
    return ip


def update_ssh_config_hostname(host: str, ip: str, *, path: Path = SSH_CONFIG_PATH) -> bool:
    """``~/.ssh/config`` の ``Host <host>`` に現在の Public IP を設定する。"""
    if not path.exists():
        print(f"{COMMAND_LABEL}: {path} が見つかりません。SSH config の更新をスキップします。", file=sys.stderr)
        return False

    lines = path.read_text(encoding="utf-8").splitlines()
    host_pattern = re.compile(r"^\s*Host\s+(.+?)\s*$", re.IGNORECASE)
    hostname_pattern = re.compile(r"^(\s*)HostName\s+\S+\s*$", re.IGNORECASE)

    target_start: int | None = None
    target_end = len(lines)
    for index, line in enumerate(lines):
        host_match = host_pattern.match(line)
        if not host_match:
            continue
        if target_start is not None:
            target_end = index
            break
        if host in host_match.group(1).split():
            target_start = index

    if target_start is None:
        print(
            f"{COMMAND_LABEL}: SSH config に 'Host {host}' が見つかりませんでした。",
            file=sys.stderr,
        )
        return False

    for index in range(target_start + 1, target_end):
        hostname_match = hostname_pattern.match(lines[index])
        if hostname_match:
            indent = hostname_match.group(1) or "    "
            lines[index] = f"{indent}HostName {ip}"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return True

    lines.insert(target_start + 1, f"    HostName {ip}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def _wait_running(instance_id: str, region: str) -> bool:
    result = _run_aws(
        ["ec2", "wait", "instance-running", "--instance-ids", instance_id],
        region=region,
    )
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        return False
    return True


def _remote_git_pull(host: str, repo_dir: str) -> int:
    print(f"--- git pull on {host}:{repo_dir} ---")
    return subprocess.run(
        [
            "ssh",
            "-F",
            str(SSH_CONFIG_PATH),
            host,
            f"cd {repo_dir} && git pull --ff-only",
        ],
        check=False,
    ).returncode


def run_ec2_command(
    command: str,
    *,
    host: str | None = None,
    instance_id: str | None = None,
    region: str | None = None,
    update_ssh: bool = True,
    pull: bool = False,
    json_output: bool = False,
) -> int:
    if not _aws_available():
        print(
            f"{COMMAND_LABEL}: aws CLI が見つかりません。WSL2 側に AWS CLI を install してください。",
            file=sys.stderr,
        )
        return 1

    config = load_config()
    resolved_host = host or default_ec2_host(config)
    resolved_instance_id = instance_id or default_ec2_instance_id(config)
    resolved_region = region or default_ec2_region(config)
    if not resolved_instance_id or not resolved_region:
        print(
            f"{COMMAND_LABEL}: instance ID または region が未設定です。"
            "`gar setup` で workspace を設定してください。",
            file=sys.stderr,
        )
        return 1

    if command == "status":
        state = ec2_instance_state(resolved_instance_id, resolved_region)
        ip = ec2_public_ip(resolved_instance_id, resolved_region) if state is not None else None
        if json_output:
            print(
                json.dumps(
                    {
                        "command": "sim status",
                        "instance_id": resolved_instance_id,
                        "region": resolved_region,
                        "state": state,
                        "public_ip": ip,
                        "running": state == "running",
                        "ok": state is not None,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0 if state is not None else 1
        if state is None:
            return 1
        print(f"instance : {resolved_instance_id}")
        print(f"region   : {resolved_region}")
        print(f"state    : {state}")
        print(f"public ip: {ip or '(none)'}")
        return 0

    if command == "stop":
        result = _run_aws(
            ["ec2", "stop-instances", "--instance-ids", resolved_instance_id],
            region=resolved_region,
        )
        if result.returncode != 0:
            print(result.stderr.strip(), file=sys.stderr)
            return result.returncode
        print(f"{COMMAND_LABEL}: shutdown 要求を送信しました ({resolved_instance_id})")
        return 0

    if command == "start":
        result = _run_aws(
            ["ec2", "start-instances", "--instance-ids", resolved_instance_id],
            region=resolved_region,
        )
        if result.returncode != 0:
            print(result.stderr.strip(), file=sys.stderr)
            return result.returncode
        print(f"{COMMAND_LABEL}: boot 要求を送信しました ({resolved_instance_id})。running を待機します...")

        if not _wait_running(resolved_instance_id, resolved_region):
            return 1

        ip = ec2_public_ip(resolved_instance_id, resolved_region)
        if ip is None:
            print(f"{COMMAND_LABEL}: public IP を取得できませんでした。", file=sys.stderr)
            return 1
        print(f"{COMMAND_LABEL}: running. public ip = {ip}")

        if update_ssh:
            if update_ssh_config_hostname(resolved_host, ip):
                print(f"{COMMAND_LABEL}: SSH config の Host {resolved_host} を {ip} に更新しました。")

        if pull:
            repo_dir = ec2_repo_dir(config)
            if repo_dir:
                return _remote_git_pull(resolved_host, repo_dir)
            print(
                f"{COMMAND_LABEL}: --pull が指定されましたが ec2.repo_dir が未設定のため git pull をスキップします。",
                file=sys.stderr,
            )
        return 0

    print(f"unknown simulation VM command: {command}", file=sys.stderr)
    return 1
