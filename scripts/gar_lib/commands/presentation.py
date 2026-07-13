"""CLI presentation for application command outcomes."""

from __future__ import annotations

import json
import sys

from scripts.gar_lib.application import CommandOutcome
from scripts.gar_lib.core.command import (
    SIM_CLEAN,
    SIM_HOST_START,
    SIM_HOST_STATUS,
    SIM_HOST_STOP,
    SIM_RUNTIME_BUILD,
    SIM_RUNTIME_DEPLOY,
    SIM_RUNTIME_DIAG,
    GarCommand,
)


def render_outcome(command: GarCommand, outcome: CommandOutcome, *, json_output: bool) -> None:
    if command == SIM_CLEAN:
        print("Simulation artifactを削除しました。")
        return

    if command in {SIM_RUNTIME_BUILD, SIM_RUNTIME_DEPLOY} and outcome.artifact is None:
        print("このsimulation environmentには個別のruntime artifactは不要です。")
        return

    if outcome.artifact is not None:
        print(f"Artifact: {outcome.artifact.bundle_path}")
        return

    if command == SIM_HOST_START and outcome.host_start is not None:
        result = outcome.host_start
        print(f"gar sim host: running. public ip = {result.state.public_ip}")
        if result.address_updated:
            print(
                f"gar sim host: SSH config の Host {result.state.host} を "
                f"{result.state.public_ip} に更新しました。"
            )
        if result.repository_updated:
            print("gar sim host: simulation hostのrepositoryを更新しました。")
        if result.repository_update_skipped:
            print(
                "gar sim host: --pullが指定されましたがec2.repo_dirが未設定のため、"
                "git pullをスキップしました。",
                file=sys.stderr,
            )
        return

    if command == SIM_HOST_STOP:
        instance_id = outcome.workspace.ec2.get("instance_id", "(unknown)")
        print(f"gar sim host: shutdown要求を送信しました ({instance_id})")
        return

    if command == SIM_HOST_STATUS and outcome.host_state is not None:
        if json_output:
            print(json.dumps(outcome.host_state.to_payload(), ensure_ascii=False, indent=2))
        else:
            print(f"instance : {outcome.host_state.instance_id}")
            print(f"region   : {outcome.host_state.region}")
            print(f"state    : {outcome.host_state.state}")
            print(f"public ip: {outcome.host_state.public_ip or '(none)'}")
        return

    if command == SIM_RUNTIME_DIAG and outcome.diagnostic is not None:
        host = outcome.workspace.ec2.get("host")
        payload = outcome.diagnostic.to_payload(host=host if isinstance(host, str) else None)
        if json_output:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            _print_diagnostic(payload)
        return

    if outcome.hardware is not None:
        outcome.hardware.render(json_output=json_output)


def _print_diagnostic(payload: dict[str, object]) -> None:
    print(f"status: {'ok' if payload.get('ok') is True else 'error'}")
    if payload.get("host"):
        print(f"host: {payload['host']}")
    if payload.get("error"):
        print(f"error: {payload['error']}")
    processes = payload.get("processes")
    if isinstance(processes, list):
        print(f"processes: {len(processes)}")
        for process in processes:
            if isinstance(process, dict):
                print(f"  {process.get('pid', '?')}: {process.get('cmd', '')}")
    devices = payload.get("devices")
    if isinstance(devices, dict):
        print("devices:")
        for path, available in devices.items():
            print(f"  {path}: {'OK' if available else 'missing'}")
    if payload.get("api") is not None:
        print("api:")
        print(json.dumps(payload["api"], ensure_ascii=False, indent=2))
