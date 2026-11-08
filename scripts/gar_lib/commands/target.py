"""CLI definition and adapter for ``gar target <action>``."""

from __future__ import annotations

import argparse
import sys
from argparse import Namespace
from collections.abc import Mapping

from scripts.gar_lib.api import Gar, TargetPreflightResult
from scripts.gar_lib.commands.capabilities import add_capability_options
from scripts.gar_lib.commands.recovery import report_access_failure
from scripts.gar_lib.commands.result import json_boundary
from scripts.gar_lib.commands.terminal import run_terminal_run_command
from scripts.gar_lib.commands.workspace_resolver import resolve_workspace
from scripts.gar_lib.core.command import GarCommand
from scripts.gar_lib.core.errors import AccessConnectionError, GarDomainError
from scripts.gar_lib.core.observation import component, unavailable
from scripts.gar_lib.core.output import JSON_OUTPUT, emit_json
from scripts.gar_lib.target.file_transfer import TargetConfigurationReport
from scripts.gar_lib.target.lifecycle import (
    TargetDeploymentConvergenceError,
    TargetDeploymentReport,
    TargetDiagnosticReport,
    TargetLifecycleResult,
)

TARGET_ACTIONS = {
    "trace": "実機の会話を止めずに音声入出力の順序を一時観測します",
    "audio": "専用の認証画面で実機音量の保存とUSB再接続時の復元を設定します",
    "wifi": "専用の認証画面で実機のWi-Fi自動接続を設定します",
    "probe": "Productで宣言した実機診断を実行します（build/deployやservice再起動なし）",
    "configure": "applicationの永続設定ファイルを明示的に配置します",
    "prepare": "SSH実機の限定sudoデプロイ権限を初回だけ設定します",
    "build": "config済みtargetの実機用artifactをビルドします",
    "preflight": "最新artifactと接続Targetの互換性を配置前に読み取り専用で検証します",
    "deploy": "target runtime へ成果物を配置します",
    "start": "配置済みapplicationをTarget recipe経由で起動・再収束し、healthとbuild IDを確認します",
    "stop": "stop対応recipeでapplicationを停止します（Targetの電源は操作しません）",
    "fetch": "BuildEnvironment から artifact store へbundleを取得します",
    "status": "Target recipe経由でapplicationの稼働状態を取得します",
    "log": "Target recipe経由でapplication logを取得します",
    "diag": "Target recipe経由でhealthと稼働build IDを診断します",
}


def add_target_parser(
    subparsers: argparse._SubParsersAction,
) -> dict[str, argparse.ArgumentParser]:
    """Register the complete ``gar target`` CLI surface and return its help parser."""

    workspace_option = argparse.ArgumentParser(add_help=False)
    workspace_option.add_argument(
        "--workspace",
        default=argparse.SUPPRESS,
        metavar="NAME",
        help="gar config で登録した workspace 名。登録が1件なら省略できます",
    )
    target_parser = subparsers.add_parser(
        "target",
        help="接続先が提供する I/O を使う実機 target を操作します",
    )
    target_parser.set_defaults(help_target="target")
    add_capability_options(target_parser, group="target")
    action_parsers = target_parser.add_subparsers(dest="action", metavar="action")
    for action, help_text in TARGET_ACTIONS.items():
        action_parser = action_parsers.add_parser(
            action,
            help=help_text,
            parents=[workspace_option],
        )
        action_parser.set_defaults(gar_command=GarCommand("target", None, action))
        if action in TARGET_ACTIONS:
            action_parser.add_argument(
                "--json",
                dest="json_output",
                action="store_true",
                default=argparse.SUPPRESS,
                help="結果を機械可読な JSON で出力します（AI / CI 向け）",
            )
        if action == "configure":
            action_parser.add_argument("--app", required=True, metavar="NAME", help="設定するapplication名")
            action_parser.add_argument("--file", required=True, metavar="PATH", help="配置するenv形式の設定ファイル")
        if action == "probe":
            action_parser.add_argument("--probe", default="status", help="Productが宣言する診断名（既定: status）")
        if action == "wifi":
            action_parser.add_argument("--transport", choices=("serial", "ssh"), default="ssh", help="実機への設定経路")
            action_parser.add_argument("--check", action="store_true", help="設定を書き込まず管理経路を確認")
            action_parser.add_argument("--repair-host", help="既存のホスト鍵で照合するWi-Fi側の復旧アドレス")
        if action in {"preflight", "start", "stop", "status", "log", "diag"}:
            action_parser.add_argument(
                "--app",
                default=None,
                metavar="NAME",
                help="対象application名。省略時は最新artifactのentrypointから解決します",
            )
        if action == "log":
            action_parser.add_argument(
                "--lines",
                type=int,
                default=200,
                metavar="N",
                help="取得する末尾log行数（既定: 200）",
            )
    return {"target": target_parser}


def run_target_command(
    args: Namespace,
    *,
    subcommand_parsers: Mapping[str, argparse.ArgumentParser] | None = None,
) -> int:
    """Run a target command, enforcing the stdout-only JSON boundary."""

    if getattr(args, "json_output", False) and not JSON_OUTPUT.get():
        return json_boundary(args, lambda: _run_target_command(args, subcommand_parsers=subcommand_parsers))
    return _run_target_command(args, subcommand_parsers=subcommand_parsers)


def _run_target_command(
    args: Namespace,
    *,
    subcommand_parsers: Mapping[str, argparse.ArgumentParser] | None = None,
) -> int:
    """Resolve and run every command below ``gar target``."""

    command = getattr(args, "gar_command", None)
    if command is None:
        if subcommand_parsers is not None:
            subcommand_parsers["target"].print_help()
        return 1
    if not isinstance(command, GarCommand) or command.group != "target":
        group = getattr(command, "group", type(command).__name__)
        raise GarDomainError(f"target command ではありません: {group}")

    workspace_selector = getattr(args, "workspace", None)
    json_output = bool(getattr(args, "json_output", False))
    try:
        workspace = resolve_workspace(workspace_selector)
        args._gar_workspace = workspace
    except GarDomainError as error:
        if json_output and command.action in TARGET_ACTIONS:
            _render_error(
                command.action,
                str(error),
                workspace=workspace_selector,
                target_id=None,
                details={},
                app=getattr(args, "app", None),
                source=getattr(args, "file", None),
            )
        else:
            print(f"gar: {error}", file=sys.stderr)
        return 1
    try:
        if command.subject is not None:
            raise GarDomainError(f"target commandにsubjectはありません: {command.subject}")
        if command.action not in TARGET_ACTIONS:
            raise GarDomainError(f"未対応の target action: {command.action}")
        target_api = Gar(workspace).target
        match command.action:
            case "trace":
                from scripts.gar_lib.target.wifi import trace_conversation

                report = trace_conversation(workspace)
                emit_json(report)
                return 0 if report["ok"] else 1
            case "audio":
                from scripts.gar_lib.target.wifi import configure_audio

                report = configure_audio(workspace)
                emit_json(report)
                return 0 if report["ok"] else 1
            case "wifi":
                from scripts.gar_lib.target.wifi import configure_wifi

                report = configure_wifi(workspace, args.transport, args.check, args.repair_host)
                emit_json(report)
                return 0 if report["ok"] else 1
            case "probe":
                from scripts.gar_lib.target.probe import run_target_probe

                report = run_target_probe(workspace, args.probe)
                if json_output:
                    emit_json(report)
                else:
                    import json

                    print(json.dumps(report, ensure_ascii=False, indent=2))
                return 0 if report["ok"] else 1
            case "configure":
                report = target_api.configure(app=args.app, file=args.file)
                _render_configuration(
                    report,
                    workspace=workspace.name,
                    target_id=workspace.selected_target,
                    json_output=json_output,
                )
                return 0
            case "prepare":
                target_api.prepare()
                print("Target preparation completed.")
                return 0
            case "build":
                artifact = target_api.build()
            case "preflight":
                report = target_api.preflight(app=getattr(args, "app", None))
                _render_preflight(
                    report,
                    workspace=workspace.name,
                    target_id=workspace.selected_target,
                    json_output=json_output,
                )
                return report.exit_code
            case "deploy":
                if getattr(args, "json_output", False):
                    deployment = target_api.deploy_report()
                    _render_deployment(
                        deployment.report,
                        workspace=workspace.name,
                        target_id=workspace.selected_target,
                        json_output=True,
                    )
                    return deployment.report.exit_code
                artifact = target_api.deploy()
            case "fetch":
                artifact = target_api.fetch()
            case "start":
                report = target_api.start(app=getattr(args, "app", None))
                _render_deployment(
                    report,
                    workspace=workspace.name,
                    target_id=workspace.selected_target,
                    json_output=json_output,
                    action="start",
                )
                return report.exit_code
            case "status" | "stop":
                result = (
                    target_api.status(app=getattr(args, "app", None))
                    if command.action == "status"
                    else target_api.stop(app=getattr(args, "app", None))
                )
                _render_lifecycle_result(
                    result,
                    workspace=workspace.name,
                    target_id=workspace.selected_target,
                    json_output=getattr(args, "json_output", False),
                )
                return result.exit_code
            case "log":
                result = target_api.log(
                    app=getattr(args, "app", None),
                    lines=getattr(args, "lines", 200),
                )
                _render_lifecycle_result(
                    result,
                    workspace=workspace.name,
                    target_id=workspace.selected_target,
                    json_output=getattr(args, "json_output", False),
                )
                return result.exit_code
            case "diag":
                report = target_api.diag(app=getattr(args, "app", None))
                _render_diagnostic(
                    report,
                    workspace=workspace.name,
                    target_id=workspace.selected_target,
                    json_output=getattr(args, "json_output", False),
                )
                return report.exit_code
            case _:
                raise GarDomainError(f"未対応の target action: {command.action}")
        print(f"Artifact: {artifact.bundle_path}")
        return 0
    except AccessConnectionError as error:
        if json_output:
            access_details = {
                "channel": error.channel,
                "endpoint": error.endpoint,
                "reason": error.reason,
                "exit_code": error.returncode,
            }
            _render_error(
                command.action,
                str(error),
                workspace=workspace.name,
                target_id=workspace.selected_target,
                details={"access": access_details} if command.action == "preflight" else access_details,
                app=getattr(args, "app", None),
                source=getattr(args, "file", None),
            )
            return 1
        return report_access_failure(
            error,
            workspace=workspace,
            retry_command=command.to_cli(
                workspace=workspace_selector,
            ),
            purpose="target",
            run_terminal=run_terminal_run_command,
        )
    except TargetDeploymentConvergenceError as error:
        _render_deployment(
            error.report,
            workspace=workspace.name,
            target_id=workspace.selected_target,
            json_output=json_output,
            action=command.action,
        )
        if not json_output:
            print(f"gar: {error}", file=sys.stderr)
            access_error = _caused_by_access_failure(error)
            if access_error is not None:
                return report_access_failure(
                    access_error,
                    workspace=workspace,
                    retry_command=command.to_cli(workspace=workspace_selector),
                    purpose="target",
                    run_terminal=run_terminal_run_command,
                )
        return error.report.exit_code
    except GarDomainError as error:
        if getattr(args, "json_output", False):
            details: dict[str, object] = {}
            report = getattr(error, "report", None)
            if report is not None and callable(getattr(report, "as_dict", None)):
                details["compatibility"] = report.as_dict()
            _render_error(
                command.action,
                str(error),
                workspace=workspace.name,
                target_id=workspace.selected_target,
                details=details,
                app=getattr(args, "app", None),
                source=getattr(args, "file", None),
            )
        else:
            print(f"gar: {error}", file=sys.stderr)
        return 1


def _render_lifecycle_result(
    result: TargetLifecycleResult,
    *,
    workspace: str,
    target_id: str | None,
    json_output: bool,
) -> None:
    if json_output:
        payload = result.to_payload()
        if result.action == "status":
            payload["components"] = _target_components(result.ok, verification="service_state")
        payload["workspace"] = workspace
        payload["target_id"] = target_id
        emit_json(payload)
        return
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
    if not result.stdout and not result.stderr:
        print(f"{result.application}: {'ok' if result.ok else 'failed'}")


def _render_preflight(
    result: TargetPreflightResult,
    *,
    workspace: str,
    target_id: str | None,
    json_output: bool,
) -> None:
    payload = {
        "schema_version": 1,
        "command": "target.preflight",
        "workspace": workspace,
        "target_id": target_id,
        "app": result.application.name,
        "build_id": result.build_id,
        "artifact_path": str(result.artifact.bundle_path),
        "compatible": result.compatible,
        "ok": result.ok,
        "exit_code": result.exit_code,
        "compatibility": result.compatibility.as_dict(),
    }
    if json_output:
        emit_json(payload)
        return
    print(f"Artifact: {result.artifact.bundle_path}")
    print(f"Application: {result.application.name}")
    print(f"Build ID: {result.build_id}")
    print("Compatibility: OK")


def _render_configuration(
    report: TargetConfigurationReport,
    *,
    workspace: str,
    target_id: str | None,
    json_output: bool,
) -> None:
    payload = {
        "schema_version": 1,
        "command": "target.configure",
        "workspace": workspace,
        "target_id": target_id,
        "app": report.application,
        "source": str(report.source),
        "destination": report.destination,
        "hash": report.sha256,
        "configured": report.configured,
        "ok": report.ok,
    }
    if json_output:
        emit_json(payload)
        return
    print(f"Application: {report.application}")
    print(f"Source: {report.source}")
    print(f"Destination: {report.destination}")
    print(f"SHA-256: {report.sha256}")
    print("Configuration: OK")


def _render_diagnostic(
    report: TargetDiagnosticReport,
    *,
    workspace: str,
    target_id: str | None,
    json_output: bool,
) -> None:
    payload = report.to_payload(workspace=workspace, target_id=target_id)
    payload["components"] = _target_components(report.ok, verification="health_and_build_id")
    if json_output:
        emit_json(payload)
        return
    print(f"application      : {report.application.name}")
    print(f"status           : {'running' if report.status.ok else 'not running'}")
    print(f"health           : {'healthy' if report.health.ok else 'unhealthy'}")
    print(f"expected build ID: {report.application.expected_build_id or '(unknown)'}")
    print(f"running build ID : {report.running_build_id or '(none)'}")
    print(f"result           : {'OK' if report.ok else 'FAIL'}")


def _target_components(ok: bool, *, verification: str) -> dict[str, object]:
    return {
        "host": unavailable("physical Targetの電源状態は管理しません"),
        "connection": component("reachable", True),
        "runtime": unavailable("process managerはTarget recipeが所有します"),
        "app": component("running" if ok else "degraded", ok, verification=verification),
    }


def _render_deployment(
    report: TargetDeploymentReport,
    *,
    workspace: str,
    target_id: str | None,
    json_output: bool,
    action: str = "deploy",
) -> None:
    payload = report.to_payload(workspace=workspace, target_id=target_id)
    if action == "start":
        payload["command"] = "target.start"
        for field in ("placed", "partial", "placed_destinations", "rollback"):
            payload.pop(field, None)
    if json_output:
        emit_json(payload)
        return
    print(f"Artifact: {report.artifact_path}")
    if action == "deploy":
        placement = "partial" if report.partial else "complete" if report.placed else "not placed"
        print(f"Placement: {placement}")
        if report.placed_destinations:
            print(f"Placed destinations: {', '.join(report.placed_destinations)}")
    if report.diagnostic is None:
        print("Target lifecycle verification: unavailable")
        return
    print(f"Application: {report.application.name if report.application is not None else '(unknown)'}")
    print(f"Running build ID: {report.diagnostic.running_build_id or '(none)'}")
    print(f"Health: {'OK' if report.diagnostic.ok else 'FAIL'}")


def _render_error(
    action: str,
    message: str,
    *,
    workspace: str | None,
    target_id: str | None,
    details: Mapping[str, object],
    app: str | None = None,
    source: str | None = None,
) -> None:
    payload: dict[str, object] = {
        "schema_version": 1,
        "command": f"target.{action}",
        "workspace": workspace,
        "target_id": target_id,
        "ok": False,
        "error": message,
    }
    if action == "deploy":
        payload.update(
            {
                "placed": False,
                "partial": False,
                "placed_destinations": [],
                "running": False,
                "rollback": {"available": False, "attempted": False},
            }
        )
    if action == "preflight":
        report = details.get("compatibility")
        build_id = report.get("artifact_build_id") if isinstance(report, dict) else None
        payload.update(
            {
                "app": app,
                "build_id": build_id,
                "compatible": False,
                "exit_code": 1,
            }
        )
    if action == "configure":
        payload.update(
            {
                "app": app,
                "source": source,
                "destination": f"/etc/gar/{app}.env" if app else None,
                "hash": None,
                "configured": False,
            }
        )
    payload.update(details)
    if action in {"status", "diag"}:
        components = _target_components(False, verification="not_checked")
        components["connection"] = component(
            "unreachable" if details.get("channel") else "unknown", False, error=message
        )
        components["app"] = component("unknown", False, verification="not_checked")
        payload["components"] = components
    emit_json(payload)


def _caused_by_access_failure(error: BaseException) -> AccessConnectionError | None:
    """Find a transport failure preserved below a post-placement report."""

    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        if isinstance(current, AccessConnectionError):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None
