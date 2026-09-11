"""Action-first simulation CLI, with subject-first compatibility aliases."""

from __future__ import annotations

import argparse
import json
import sys
from argparse import Namespace
from collections.abc import Mapping, Sequence

from scripts.gar_lib.api import Gar
from scripts.gar_lib.commands.action_surface import (
    add_action_parser,
    hide_compatibility_parsers,
    validate_action_options,
)
from scripts.gar_lib.commands.capabilities import add_capability_options
from scripts.gar_lib.commands.infra import run_sim_infra_command
from scripts.gar_lib.commands.recovery import report_access_failure
from scripts.gar_lib.commands.result import render_observation
from scripts.gar_lib.commands.terminal import run_terminal_run_command
from scripts.gar_lib.commands.workspace_resolver import resolve_workspace
from scripts.gar_lib.core.artifact import Artifact
from scripts.gar_lib.core.command import GarCommand
from scripts.gar_lib.core.command_surface import SIM_ACTION_SURFACE
from scripts.gar_lib.core.errors import AccessConnectionError, GarDomainError
from scripts.gar_lib.core.output import emit_json
from scripts.gar_lib.simulation.deployment import SimulationDeploymentError, placement_payload
from scripts.gar_lib.simulation.diagnostics.model import SimulationDiagnosticReport
from scripts.gar_lib.simulation.hardware.control import HardwareControlResult
from scripts.gar_lib.simulation.host.contract import (
    SimulationHostStartResult,
    SimulationHostState,
)
from scripts.gar_lib.simulation.host.prepare import prepare_simulation_host

# Subject capabilities also define compatibility parsers and their shared options.
# The public action-first vocabulary lives in core.command_surface.
SIM_ACTIONS: dict[str, dict[str, str]] = {
    "app": {
        "build": "product の simulation build hook を実行します",
        "clean": "product の simulation build artifact を削除します",
        "deploy": "product application を simulation runtime へ配置します",
    },
    "runtime": {
        "build": "仮想デバイス stub（CUSE I2C/SPI など）や Wokwi firmware をビルドします",
        "deploy": "simulation runtime を host へ配置します",
        "start": "simulation runtime を起動します",
        "stop": "simulation runtime を停止します",
        "status": "simulation runtime の状態を確認します",
        "log": "simulation runtime のログを表示します",
        "diag": "simulation runtime を診断します",
    },
    "host": {
        "start": "simulation host を起動します",
        "stop": "simulation host を停止します",
        "status": "simulation host の状態を確認します",
    },
    "gpio": {
        "install": "GPIO dummy runtime を host へ配置します",
        "start": "GPIO dummy runtime を起動します",
        "stop": "GPIO dummy runtime を停止します",
        "plan": "hardware 定義から生成する GPIO runtime の内容を表示します",
        "status": "GPIO dummy runtime の状態を確認します",
        "check": "GPIO dummy runtime の kernel 側前提条件を確認します",
    },
    "io": {
        "state": "virtual H/W の現在値を取得します",
        "press": "button を押下します（--device 必須）",
        "set": "device の値を設定します（--device 必須）",
        "clear": "device の値を解除します（--device 必須）",
    },
}


def _shared_option(*args: object, **kwargs: object) -> argparse.ArgumentParser:
    """複数のleaf parserで共有するoptionを1回だけ定義する。"""

    option = argparse.ArgumentParser(add_help=False)
    option.add_argument(*args, **kwargs)  # type: ignore[arg-type]
    return option


def _selected_actions(subject: str, *names: str) -> dict[str, str]:
    return {name: SIM_ACTIONS[subject][name] for name in names}


def _add_actions(
    subparsers: argparse._SubParsersAction,
    subject: str,
    actions: Mapping[str, str],
    *,
    parents: Sequence[argparse.ArgumentParser] = (),
) -> dict[str, argparse.ArgumentParser]:
    """Add leaf parsers whose execution is resolved later from ``GarCommand``."""

    created: dict[str, argparse.ArgumentParser] = {}
    for action, help_text in actions.items():
        leaf = subparsers.add_parser(action, help=help_text, parents=list(parents))
        leaf.set_defaults(gar_command=GarCommand("sim", subject, action))
        created[action] = leaf
    return created


def _print_help(
    subcommand_parsers: Mapping[str, argparse.ArgumentParser] | None,
    target: str,
) -> None:
    if subcommand_parsers is not None:
        subcommand_parsers[target].print_help()


def add_sim_parser(
    subparsers: argparse._SubParsersAction,
) -> dict[str, argparse.ArgumentParser]:
    """Register the complete ``gar sim`` CLI surface and return its help parsers."""

    workspace_option = _shared_option(
        "--workspace",
        default=argparse.SUPPRESS,
        metavar="NAME",
        help="gar config で登録した workspace 名。登録が1件なら省略できます",
    )
    json_option = _shared_option(
        "--json",
        dest="json_output",
        action="store_true",
        default=argparse.SUPPRESS,
        help="結果を機械可読な JSON で出力します（AI / CI 向け）",
    )
    workspace_json = (workspace_option, json_option)

    sim_parser = subparsers.add_parser(
        "sim", help="simulation の host / runtime / application / virtual H/W を操作します"
    )
    sim_parser.set_defaults(help_target="sim")
    sim_subparsers = sim_parser.add_subparsers(dest="sim_subject", metavar="action")
    sim_parser.epilog = "互換: gar sim <app|runtime|host> <action> も引き続き利用できます。"
    add_capability_options(sim_parser, group="sim")

    prepare_parser = sim_subparsers.add_parser(
        "prepare", help=SIM_ACTION_SURFACE["prepare"].description, parents=[workspace_option, json_option]
    )
    prepare_parser.set_defaults(gar_command=GarCommand("sim", None, "prepare"))

    sim_app_parser = sim_subparsers.add_parser(
        "app", help="product application を simulation 向けに build / deploy します"
    )
    sim_app_parser.set_defaults(help_target="sim_app")
    sim_app_actions = _add_actions(
        sim_app_parser.add_subparsers(dest="action", metavar="action"),
        "app",
        SIM_ACTIONS["app"],
        parents=workspace_json,
    )

    sim_runtime_parser = sim_subparsers.add_parser(
        "runtime", help="simulation runtime（device stub / bridge）を操作します"
    )
    sim_runtime_parser.set_defaults(help_target="sim_runtime")
    sim_runtime_subparsers = sim_runtime_parser.add_subparsers(dest="action", metavar="action")
    sim_runtime_actions = _add_actions(
        sim_runtime_subparsers,
        "runtime",
        _selected_actions("runtime", "build", "deploy", "start", "stop", "status", "log"),
        parents=workspace_json,
    )
    sim_runtime_actions.update(
        _add_actions(
            sim_runtime_subparsers,
            "runtime",
            _selected_actions("runtime", "diag"),
            parents=workspace_json,
        )
    )
    sim_runtime_actions["start"].add_argument("--settings", default=None, help="VS Code settings.json path")
    sim_runtime_actions["start"].add_argument("--profile-name", default=None, help="VS Code terminal profile 名")
    sim_runtime_actions["start"].add_argument(
        "--panel-port",
        type=int,
        default=8080,
        choices=range(1, 65536),
        metavar="PORT",
        help="Hardware Panel を公開するローカル port（既定: 8080）",
    )
    sim_runtime_actions["start"].add_argument(
        "--no-port-forward",
        action="store_true",
        help="Hardware Panel 用の 8080 port forward を開始しません",
    )
    sim_runtime_actions["stop"].add_argument(
        "--keep-port-forward",
        action="store_true",
        help="Hardware Panel 用の port forward を停止しません",
    )

    for action in ("stop", "status"):
        sim_runtime_actions[action].add_argument(
            "--panel-port",
            type=int,
            default=8080,
            choices=range(1, 65536),
            metavar="PORT",
            help="対象のローカルport forward（既定: 8080）",
        )

    sim_host_parser = sim_subparsers.add_parser(
        "host",
        help="simulationを載せるhost（VirtualBox / AWS / container）を操作します",
    )
    sim_host_parser.set_defaults(help_target="sim_host")
    sim_host_subparsers = sim_host_parser.add_subparsers(dest="action", metavar="action")
    sim_host_actions = _add_actions(
        sim_host_subparsers,
        "host",
        _selected_actions("host", "start", "stop"),
        parents=workspace_json,
    )
    sim_host_actions.update(
        _add_actions(
            sim_host_subparsers,
            "host",
            _selected_actions("host", "status"),
            parents=workspace_json,
        )
    )
    sim_host_actions["start"].add_argument(
        "--no-update-ssh",
        action="store_true",
        help="起動後に ~/.ssh/config の HostName を更新しません",
    )
    sim_host_actions["start"].add_argument(
        "--pull",
        action="store_true",
        help="起動後に repo_dir で git pull を実行します",
    )

    subject_actions = {"app": sim_app_actions, "runtime": sim_runtime_actions, "host": sim_host_actions}
    for action, spec in SIM_ACTION_SURFACE.items():
        if action == "prepare":
            continue
        add_action_parser(
            sim_subparsers,
            group="sim",
            action=action,
            spec=spec,
            subjects={subject: subject_actions[subject][action] for subject in spec.subjects},
        )
    hide_compatibility_parsers(sim_subparsers, ("app", "runtime", "host"))

    sim_gpio_parser = sim_subparsers.add_parser(
        "gpio",
        help="GPIO dummy runtime を生成・配置・確認します",
    )
    sim_gpio_parser.set_defaults(help_target="sim_gpio")
    sim_gpio_subparsers = sim_gpio_parser.add_subparsers(dest="action", metavar="action")
    _add_actions(
        sim_gpio_subparsers,
        "gpio",
        _selected_actions("gpio", "install", "start", "stop"),
        parents=(workspace_option,),
    )
    _add_actions(
        sim_gpio_subparsers,
        "gpio",
        _selected_actions("gpio", "plan", "status", "check"),
        parents=workspace_json,
    )

    sim_io_parser = sim_subparsers.add_parser(
        "io",
        help="共通 Bridge control plane 経由で virtual H/W を操作します（AI / CI 向け）",
    )
    sim_io_parser.set_defaults(help_target="sim_io")
    io_actions = sim_io_parser.add_subparsers(dest="action", metavar="action")
    state_parser = io_actions.add_parser(
        "state",
        help=SIM_ACTIONS["io"]["state"],
        parents=list(workspace_json),
    )
    state_parser.set_defaults(gar_command=GarCommand("sim", "io", "state"))

    press_parser = io_actions.add_parser(
        "press",
        help=SIM_ACTIONS["io"]["press"],
        parents=list(workspace_json),
    )
    press_parser.set_defaults(gar_command=GarCommand("sim", "io", "press"))
    press_parser.add_argument("--device", choices=("button",), required=True)
    press_parser.add_argument("--button", default=None)
    press_parser.add_argument("--line", default=None)
    press_parser.add_argument("--duration-ms", type=int, default=150)

    set_parser = io_actions.add_parser(
        "set",
        help=SIM_ACTIONS["io"]["set"],
        parents=list(workspace_json),
    )
    set_parser.set_defaults(gar_command=GarCommand("sim", "io", "set"))
    set_parser.add_argument("--device", choices=("button", "rfid", "range"), required=True)
    set_parser.add_argument("--button", default=None)
    set_parser.add_argument("--line", default=None)
    set_parser.add_argument("--value", default=None)
    set_parser.add_argument("--uid", default=None)

    clear_parser = io_actions.add_parser(
        "clear",
        help=SIM_ACTIONS["io"]["clear"],
        parents=list(workspace_json),
    )
    clear_parser.set_defaults(gar_command=GarCommand("sim", "io", "clear"))
    clear_parser.add_argument("--device", choices=("rfid",), required=True)

    sim_infra_parser = sim_subparsers.add_parser("infra", help="simulation host インフラを Terraform で管理します")
    sim_infra_parser.set_defaults(help_target="sim_infra")
    sim_infra_subparsers = sim_infra_parser.add_subparsers(dest="infra_action", metavar="action")
    for infra_action in ("setup", "apply", "destroy"):
        infra_action_parser = sim_infra_subparsers.add_parser(infra_action, help=f"terraform {infra_action}")
        infra_action_parser.add_argument("--key-name", default=None, help="EC2 SSH key pair name")
        infra_action_parser.add_argument("--region", default=None, help="AWS region")
        infra_action_parser.add_argument(
            "--ssh-cidr",
            default=None,
            help="SSHを許可する接続元CIDR（例: 203.0.113.4/32）",
        )
        infra_action_parser.add_argument(
            "--auto-approve",
            action="store_true",
            help="--auto-approve を terraform に渡します",
        )

    return {
        "sim": sim_parser,
        "sim_app": sim_app_parser,
        "sim_runtime": sim_runtime_parser,
        "sim_host": sim_host_parser,
        "sim_gpio": sim_gpio_parser,
        "sim_io": sim_io_parser,
        "sim_infra": sim_infra_parser,
    }


def run_sim_command(
    args: Namespace,
    *,
    subcommand_parsers: Mapping[str, argparse.ArgumentParser] | None = None,
) -> int:
    """Resolve and run every command below ``gar sim``."""

    if getattr(args, "sim_subject", None) == "infra":
        if getattr(args, "json_output", False):
            raise GarDomainError("sim infraは--jsonに未対応です")
        if args.infra_action is None:
            _print_help(subcommand_parsers, "sim_infra")
            return 1
        return run_sim_infra_command(
            args.infra_action,
            key_name=getattr(args, "key_name", None),
            region=getattr(args, "region", None),
            ssh_cidr=getattr(args, "ssh_cidr", None),
            auto_approve=getattr(args, "auto_approve", False),
        )

    command = getattr(args, "gar_command", None)
    if command is None:
        _print_help(
            subcommand_parsers,
            getattr(args, "help_target", "sim"),
        )
        return 1
    if not isinstance(command, GarCommand) or command.group != "sim":
        group = getattr(command, "group", type(command).__name__)
        raise GarDomainError(f"simulation command ではありません: {group}")

    workspace_selector = getattr(args, "workspace", None)
    try:
        validate_action_options(args)
        workspace = resolve_workspace(workspace_selector)
        args._gar_workspace = workspace
    except GarDomainError as error:
        print(f"gar: {error}", file=sys.stderr)
        return 1

    try:
        if command.action == "prepare":
            prepare_simulation_host(workspace)
            print("Simulation host preparation completed.")
            return 0
        subject_name = command.subject
        actions = {"build", "deploy", "status", "diag"} if subject_name is None else SIM_ACTIONS.get(subject_name, {})
        if command.action not in actions:
            raise GarDomainError(f"未対応の simulation command: {subject_name or '(none)'} {command.action}")
        return _run_simulation_action(Gar(workspace), command, args)
    except AccessConnectionError as error:
        if getattr(args, "json_output", False):
            raise
        device = getattr(args, "device", None)
        return report_access_failure(
            error,
            workspace=workspace,
            retry_command=command.to_cli(
                workspace=workspace_selector,
                options=("--device", str(device)) if device else (),
            ),
            purpose="simulation",
            run_terminal=run_terminal_run_command,
        )
    except SimulationDeploymentError as error:
        if getattr(args, "json_output", False):
            raise
        print(f"gar: {error}", file=sys.stderr)
        print(f"配置済みartifact: {error.details['placed_artifacts']}", file=sys.stderr)
        print("失敗したartifactも一部配置済みの可能性があります。稼働確認・rollbackは未実行です。", file=sys.stderr)
        return 1
    except GarDomainError as error:
        print(f"gar: {error}", file=sys.stderr)
        return 1


def _run_simulation_action(gar: Gar, command: GarCommand, args: Namespace) -> int:
    """Call the public API explicitly so signatures remain visible to readers and type checkers."""

    match command.subject:
        case None:
            match command.action:
                case "status":
                    return render_observation(gar.sim.status(), json_output=getattr(args, "json_output", False))
                case "diag":
                    return render_observation(gar.sim.diag(), json_output=getattr(args, "json_output", False))
                case "build":
                    artifacts = gar.sim.build()
                case "deploy":
                    artifacts = gar.sim.deploy()
                case _:
                    raise GarDomainError(f"未対応の simulation action: {command.action}")
            if getattr(args, "json_output", False) and command.action == "deploy":
                emit_json({"ok": True, "placed": True, "partial": False, **placement_payload(artifacts)})
                return 0
            for artifact in artifacts:
                _render_artifact(artifact)
            if command.action == "deploy":
                print(
                    "Placement completed. Running/health: not checked. 次に gar sim start / diag を実行してください。"
                )
            return 0
        case "app":
            return _run_app_action(gar, command.action)
        case "runtime":
            return _run_runtime_action(gar, command.action, args)
        case "host":
            return _run_host_action(gar, command.action, args)
        case "gpio":
            return _run_gpio_action(gar, command.action, args)
        case "io":
            return _run_io_action(gar, command.action, args)
        case _:
            raise GarDomainError(f"未対応の simulation subject: {command.subject or '(none)'}")


def _run_app_action(gar: Gar, action: str) -> int:
    match action:
        case "build":
            return _render_artifact(gar.sim.app.build())
        case "clean":
            gar.sim.app.clean()
            print("Simulation artifactを削除しました。")
            return 0
        case "deploy":
            return _render_artifact(gar.sim.app.deploy())
        case _:
            raise GarDomainError(f"未対応の simulation app action: {action}")


def _run_runtime_action(gar: Gar, action: str, args: Namespace) -> int:
    match action:
        case "build":
            return _render_optional_runtime_artifact(gar.sim.runtime.build())
        case "deploy":
            return _render_optional_runtime_artifact(gar.sim.runtime.deploy())
        case "start":
            return gar.sim.runtime.start(
                settings=getattr(args, "settings", None),
                profile_name=getattr(args, "profile_name", None),
                no_port_forward=getattr(args, "no_port_forward", False),
                panel_port=getattr(args, "panel_port", 8080),
            )
        case "stop":
            options = {"panel_port": args.panel_port} if getattr(args, "panel_port", 8080) != 8080 else {}
            return gar.sim.runtime.stop(keep_port_forward=getattr(args, "keep_port_forward", False), **options)
        case "status":
            return (
                gar.sim.runtime.status(panel_port=args.panel_port)
                if getattr(args, "panel_port", 8080) != 8080
                else gar.sim.runtime.status()
            )
        case "log":
            return gar.sim.runtime.log()
        case "diag":
            report = gar.sim.runtime.diag()
            _render_diagnostic(
                report,
                host=gar.sim.runtime.session_host,
                json_output=getattr(args, "json_output", False),
            )
            return report.exit_code
        case _:
            raise GarDomainError(f"未対応の simulation runtime action: {action}")


def _run_host_action(gar: Gar, action: str, args: Namespace) -> int:
    match action:
        case "start":
            result = gar.sim.host.start(
                no_update_ssh=getattr(args, "no_update_ssh", False),
                pull=getattr(args, "pull", False),
            )
            _render_host_start(result)
            return 0
        case "stop":
            gar.sim.host.stop()
            print("gar sim host: shutdown要求を送信しました。")
            return 0
        case "status":
            _render_host_status(
                gar.sim.host.status(),
                json_output=getattr(args, "json_output", False),
            )
            return 0
        case _:
            raise GarDomainError(f"未対応の simulation host action: {action}")


def _run_gpio_action(gar: Gar, action: str, args: Namespace) -> int:
    match action:
        case "install":
            result = gar.sim.gpio.install()
        case "start":
            result = gar.sim.gpio.start()
        case "stop":
            result = gar.sim.gpio.stop()
        case "plan":
            result = gar.sim.gpio.plan()
        case "status":
            result = gar.sim.gpio.status()
        case "check":
            result = gar.sim.gpio.check()
        case _:
            raise GarDomainError(f"未対応の simulation gpio action: {action}")
    _render_hardware_result(result, json_output=getattr(args, "json_output", False))
    return result.exit_code


def _run_io_action(gar: Gar, action: str, args: Namespace) -> int:
    params = _io_parameters(action, args)
    try:
        match action:
            case "state":
                result = gar.sim.io.state(**params)
            case "press":
                result = gar.sim.io.press(**params)
            case "set":
                result = gar.sim.io.set(**params)
            case "clear":
                result = gar.sim.io.clear(**params)
            case _:
                raise GarDomainError(f"未対応の simulation io action: {action}")
    except (KeyError, TypeError, ValueError) as error:
        raise GarDomainError(f"simulation ioの引数が不正です: {error}") from error
    _render_hardware_result(result, json_output=getattr(args, "json_output", False))
    return result.exit_code


def _io_parameters(action: str, args: Namespace) -> dict[str, object]:
    if action == "state":
        return {}
    device = getattr(args, "device", None)
    if not isinstance(device, str) or not device:
        raise GarDomainError(f"io {action} には --device が必要です")
    params: dict[str, object] = {"device": device}
    for name in ("button", "line", "duration_ms", "value", "uid"):
        value = getattr(args, name, None)
        if value is not None:
            params[name] = value
    if action == "set" and device == "rfid" and not params.get("uid"):
        raise GarDomainError("io set --device rfid には --uid が必要です")
    if action == "set" and device == "range" and params.get("value") is None:
        raise GarDomainError("io set --device range には --value が必要です")
    return params


def _render_artifact(artifact: Artifact) -> int:
    print(f"Artifact: {artifact.bundle_path}")
    return 0


def _render_optional_runtime_artifact(artifact: Artifact | None) -> int:
    if artifact is None:
        print("このsimulation environmentには個別のruntime artifactは不要です。")
        return 0
    return _render_artifact(artifact)


def _render_host_start(result: SimulationHostStartResult) -> None:
    print(f"gar sim host: running. address = {result.state.address or '(local)'}")
    if result.address_updated:
        print(f"gar sim host: SSH config の Host {result.state.host} を " f"{result.state.address} に更新しました。")
    if result.repository_updated:
        print("gar sim host: simulation hostのrepositoryを更新しました。")
    if result.repository_update_skipped:
        print(
            "gar sim host: --pullが指定されましたがrepo_dirが未設定のため、" "git pullをスキップしました。",
            file=sys.stderr,
        )


def _render_host_status(state: SimulationHostState, *, json_output: bool) -> None:
    if json_output:
        emit_json(state.to_payload())
        return
    print(f"backend : {state.backend}")
    print(f"id      : {state.id}")
    print(f"state   : {state.state}")
    print(f"address : {state.address or '(none)'}")
    for name, value in state.details.items():
        print(f"{name:8}: {value}")


def _render_hardware_result(result: HardwareControlResult, *, json_output: bool) -> None:
    if json_output and result.payload is not None:
        emit_json(result.payload)
        return
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
    if result.payload is not None and not result.stdout:
        for key, value in result.payload.items():
            print(f"{key}: {value}")


def _render_diagnostic(
    report: SimulationDiagnosticReport,
    *,
    host: str | None,
    json_output: bool,
) -> None:
    payload = report.to_payload(host=host)
    if json_output:
        emit_json(payload)
        return
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
