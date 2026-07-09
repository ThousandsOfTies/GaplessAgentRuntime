"""`gar sim infra`: Terraform-backed simulation host management."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.gar_lib.config import (
    PROJECT_ROOT,
    default_ec2_host,
    default_ec2_instance_id,
    default_ec2_region,
    load_config,
    save_config,
    set_default_ec2_instance_id,
    set_default_ec2_region,
)
from scripts.gar_lib.environments.registry.simulator.aws_ec2 import update_ssh_config_hostname

TERRAFORM_DIR = PROJECT_ROOT / "infra" / "terraform"


def _terraform_available() -> bool:
    return shutil.which("terraform") is not None


def _run_terraform(args: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["terraform", *args],
        cwd=str(cwd),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _terraform_env(region: str | None, key_name: str | None) -> dict[str, str]:
    env = os.environ.copy()
    if region:
        env["TF_VAR_aws_region"] = region
    if key_name:
        env["TF_VAR_key_name"] = key_name
    return env


def _print_completed(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)


def _terraform_init(env: dict[str, str]) -> bool:
    result = _run_terraform(["init", "-input=false"], cwd=TERRAFORM_DIR, env=env)
    _print_completed(result)
    return result.returncode == 0


def _terraform_output_json(env: dict[str, str], *, quiet: bool = False) -> dict[str, str]:
    result = _run_terraform(["output", "-json"], cwd=TERRAFORM_DIR, env=env)
    if result.returncode != 0:
        if not quiet:
            _print_completed(result)
        return {}
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        print(f"gar sim infra: terraform output -json の解析に失敗しました: {exc}", file=sys.stderr)
        return {}

    values: dict[str, str] = {}
    if isinstance(raw, dict):
        for key, item in raw.items():
            if isinstance(item, dict) and isinstance(item.get("value"), str):
                values[key] = item["value"]
    return values


def _sync_config_from_outputs(outputs: dict[str, str], *, region: str | None) -> None:
    instance_id = outputs.get("instance_id")
    public_ip = outputs.get("public_ip")
    if not instance_id and not public_ip:
        return

    config = load_config()
    if instance_id:
        set_default_ec2_instance_id(config, instance_id)
    if region:
        set_default_ec2_region(config, region)
    save_config(config)

    if public_ip:
        host = default_ec2_host(config)
        if update_ssh_config_hostname(host, public_ip):
            print(f"gar sim infra: SSH config の Host {host} を {public_ip} に更新しました。")


def _print_current_settings(config: dict, outputs: dict[str, str], *, region: str) -> None:
    print("Current simulation infra settings:")
    print(f"  host       : {default_ec2_host(config)}")
    print(f"  region     : {region}")
    print(f"  instance_id: {outputs.get('instance_id') or default_ec2_instance_id(config) or '(none)'}")
    print(f"  public_ip  : {outputs.get('public_ip') or '(none)'}")


def run_sim_infra_command(
    command: str,
    *,
    key_name: str | None = None,
    region: str | None = None,
    auto_approve: bool = False,
) -> int:
    if not TERRAFORM_DIR.exists():
        print(f"gar sim infra: Terraform dir が見つかりません: {TERRAFORM_DIR}", file=sys.stderr)
        return 1
    if not _terraform_available():
        print("gar sim infra: terraform が見つかりません。Terraform を install してください。", file=sys.stderr)
        return 1

    config = load_config()
    resolved_region = region or default_ec2_region(config)
    env = _terraform_env(resolved_region, key_name)

    if not _terraform_init(env):
        return 1

    if command == "setup":
        _print_current_settings(config, _terraform_output_json(env, quiet=True), region=resolved_region)
        args = ["plan", "-input=false"]
    elif command == "apply":
        args = ["apply", "-input=false"]
        if auto_approve:
            args.append("-auto-approve")
    elif command == "destroy":
        args = ["destroy", "-input=false"]
        if auto_approve:
            args.append("-auto-approve")
    else:
        print(f"unknown sim infra command: {command}", file=sys.stderr)
        return 1

    result = _run_terraform(args, cwd=TERRAFORM_DIR, env=env)
    _print_completed(result)
    if result.returncode != 0:
        return result.returncode

    if command == "apply":
        outputs = _terraform_output_json(env)
        _sync_config_from_outputs(outputs, region=resolved_region)

    return 0
