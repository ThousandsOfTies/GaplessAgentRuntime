"""Readable reference CLI for the workspace-based GAR architecture.

This entry point intentionally contains only the standard ``sim`` and
``target`` use cases.  Operational helpers such as setup, terminal, USB,
artifact fetch, and explicit ESP32 commands remain in the production CLI.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from collections.abc import Sequence
from typing import NoReturn

from scripts.gar_lib.commands.sim import (
    run_sim_command,
    run_sim_diagnostic,
    run_sim_hardware_command,
    run_sim_host_command,
    run_sim_lifecycle,
    run_sim_panel,
)
from scripts.gar_lib.commands.target import run_target_command
from scripts.gar_lib.core.command import (
    SIM_BUILD,
    SIM_CLEAN,
    SIM_DEPLOY,
    SIM_RUNTIME_BUILD,
    SIM_RUNTIME_DEPLOY,
    TARGET_BUILD,
    TARGET_DEPLOY,
)


def _add_workspace(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        default=None,
        metavar="NAME",
        help="gar setupで登録したworkspace名。登録が1件なら省略できます",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gar",
        description="GAR workspace architecture reference CLI",
    )
    groups = parser.add_subparsers(dest="group", required=True)

    sim = groups.add_parser("sim", help="simulationを操作します")
    sim_commands = sim.add_subparsers(dest="sim_command", required=True)

    sim_build = sim_commands.add_parser("build", help="simulation appをビルドします")
    sim_build.add_argument("action", nargs="?", choices=("clean",))
    _add_workspace(sim_build)

    sim_deploy = sim_commands.add_parser("deploy", help="simulation appを配置します")
    _add_workspace(sim_deploy)

    for action in ("start", "stop", "status"):
        sim_host = sim_commands.add_parser(action, help=f"simulation hostを{action}します")
        _add_workspace(sim_host)
        if action == "start":
            sim_host.add_argument("--no-update-ssh", action="store_true")
            sim_host.add_argument("--pull", action="store_true")
        if action == "status":
            sim_host.add_argument("--json", dest="json_output", action="store_true")

    sim_env = sim_commands.add_parser("env", help="simulation runtimeを操作します")
    sim_env_commands = sim_env.add_subparsers(dest="sim_env_command", required=True)

    for action in ("build", "deploy"):
        sim_env_artifact = sim_env_commands.add_parser(
            action,
            help=f"simulation runtime artifactを{action}します",
        )
        _add_workspace(sim_env_artifact)

    sim_env_start = sim_env_commands.add_parser("start", help="simulation runtimeを起動します")
    _add_workspace(sim_env_start)
    sim_env_start.add_argument("--settings", default=None)
    sim_env_start.add_argument("--profile-name", default=None)
    sim_env_start.add_argument("--no-port-forward", action="store_true")

    sim_env_stop = sim_env_commands.add_parser("stop", help="simulation runtimeを停止します")
    _add_workspace(sim_env_stop)
    sim_env_stop.add_argument("--keep-port-forward", action="store_true")

    for action in ("status", "log"):
        sim_env_lifecycle = sim_env_commands.add_parser(
            action,
            help=f"simulation runtimeを{action}します",
        )
        _add_workspace(sim_env_lifecycle)

    sim_env_diag = sim_env_commands.add_parser("diag", help="simulation runtimeを診断します")
    _add_workspace(sim_env_diag)
    sim_env_diag.add_argument("--json", dest="json_output", action="store_true")

    sim_env_gpio_check = sim_env_commands.add_parser(
        "gpio-sim-check",
        help="GPIO simulation対応状況を確認します",
    )
    _add_workspace(sim_env_gpio_check)
    sim_env_gpio_check.add_argument("--json", dest="json_output", action="store_true")

    sim_gpio = sim_env_commands.add_parser("gpio", help="GPIO runtimeを操作します")
    sim_gpio_commands = sim_gpio.add_subparsers(dest="gpio_command", required=True)
    for action in ("plan", "install", "start", "stop", "status"):
        sim_gpio_action = sim_gpio_commands.add_parser(action)
        _add_workspace(sim_gpio_action)
        if action in ("plan", "status"):
            sim_gpio_action.add_argument("--json", dest="json_output", action="store_true")

    sim_panel = sim_env_commands.add_parser("panel", help="simulation hardware panelを操作します")
    sim_panel.add_argument(
        "action",
        choices=("state", "button-press", "button-set", "rfid-tap", "rfid-remove", "range-set"),
    )
    _add_workspace(sim_panel)
    sim_panel.add_argument("--button", default=None)
    sim_panel.add_argument("--line", default=None)
    sim_panel.add_argument("--duration-ms", type=int, default=150)
    sim_panel.add_argument("--value", default=None)
    sim_panel.add_argument("--uid", default=None)
    sim_panel.add_argument("--json", dest="json_output", action="store_true")

    target = groups.add_parser("target", help="実機targetを操作します")
    target_commands = target.add_subparsers(dest="target_command", required=True)
    for action in ("build", "deploy"):
        target_action = target_commands.add_parser(action, help=f"target appを{action}します")
        _add_workspace(target_action)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    command_args = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(command_args)
    retry_command = shlex.join(("gar", *command_args))

    if args.group == "sim" and args.sim_command == "build":
        return run_sim_command(
            SIM_CLEAN if args.action == "clean" else SIM_BUILD,
            workspace_selector=args.workspace,
            retry_command=retry_command,
        )

    if args.group == "sim" and args.sim_command == "deploy":
        return run_sim_command(
            SIM_DEPLOY,
            workspace_selector=args.workspace,
            retry_command=retry_command,
        )

    if args.group == "sim" and args.sim_command in ("start", "stop", "status"):
        return run_sim_host_command(
            args.sim_command,
            workspace_selector=args.workspace,
            retry_command=retry_command,
            update_address=not getattr(args, "no_update_ssh", False),
            update_repository=getattr(args, "pull", False),
            json_output=getattr(args, "json_output", False),
        )

    if args.group == "sim" and args.sim_command == "env":
        if args.sim_env_command == "build":
            return run_sim_command(
                SIM_RUNTIME_BUILD,
                workspace_selector=args.workspace,
                retry_command=retry_command,
            )

        if args.sim_env_command == "deploy":
            return run_sim_command(
                SIM_RUNTIME_DEPLOY,
                workspace_selector=args.workspace,
                retry_command=retry_command,
            )

        if args.sim_env_command in ("start", "stop", "status", "log"):
            manage_port_forward = True
            if args.sim_env_command == "start":
                manage_port_forward = not args.no_port_forward
            if args.sim_env_command == "stop":
                manage_port_forward = not args.keep_port_forward
            return run_sim_lifecycle(
                args.sim_env_command,
                workspace_selector=args.workspace,
                retry_command=retry_command,
                settings=getattr(args, "settings", None),
                profile_name=getattr(args, "profile_name", None),
                manage_port_forward=manage_port_forward,
            )

        if args.sim_env_command == "diag":
            return run_sim_diagnostic(
                workspace_selector=args.workspace,
                retry_command=retry_command,
                json_output=args.json_output,
            )

        if args.sim_env_command == "gpio-sim-check":
            return run_sim_hardware_command(
                "check",
                workspace_selector=args.workspace,
                retry_command=retry_command,
                json_output=args.json_output,
            )

        if args.sim_env_command == "gpio":
            return run_sim_hardware_command(
                args.gpio_command,
                workspace_selector=args.workspace,
                retry_command=retry_command,
                json_output=getattr(args, "json_output", False),
            )

        if args.sim_env_command == "panel":
            params = {
                key: value
                for key, value in {
                    "button": args.button,
                    "line": args.line,
                    "duration_ms": args.duration_ms,
                    "value": args.value,
                    "uid": args.uid,
                }.items()
                if value is not None
            }
            return run_sim_panel(
                args.action,
                workspace_selector=args.workspace,
                retry_command=retry_command,
                json_output=args.json_output,
                params=params,
            )

    if args.group == "target" and args.target_command == "build":
        return run_target_command(
            TARGET_BUILD,
            workspace_selector=args.workspace,
            retry_command=retry_command,
        )

    if args.group == "target" and args.target_command == "deploy":
        return run_target_command(
            TARGET_DEPLOY,
            workspace_selector=args.workspace,
            retry_command=retry_command,
        )

    return 1


def _main() -> NoReturn:
    raise SystemExit(main())


if __name__ == "__main__":
    _main()
