"""Readable reference entry point for the workspace-based GAR architecture.

The production CLI contains setup and operational helper commands as well.
This file intentionally shows only the core build/deploy sequence.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from collections.abc import Sequence
from typing import NoReturn

from scripts.gar_lib.artifacts.store import LocalArtifactStore
from scripts.gar_lib.build.resolver import ConfigBuildEnvironmentResolver
from scripts.gar_lib.commands.sim import SimulationCommandServices, dispatch_sim_command
from scripts.gar_lib.commands.target import TargetCommandServices, dispatch_target_command
from scripts.gar_lib.commands.terminal import run_terminal_request
from scripts.gar_lib.core.artifact import Artifact
from scripts.gar_lib.core.command import (
    SIM_BUILD,
    SIM_CLEAN,
    SIM_DEPLOY,
    SIM_RUNTIME_BUILD,
    SIM_RUNTIME_DEPLOY,
    TARGET_BUILD,
    TARGET_DEPLOY,
    GarCommand,
)
from scripts.gar_lib.core.errors import AccessConnectionError, GarDomainError
from scripts.gar_lib.recovery.access import AccessRecoveryPlanner
from scripts.gar_lib.recovery.terminal import TerminalBridgeRecoveryExecutor
from scripts.gar_lib.simulation.resolver import ConfigSimulationEnvironmentResolver
from scripts.gar_lib.target.resolver import ConfigTargetEnvironmentResolver
from scripts.gar_lib.workspaces.registry import ConfigWorkspaceRegistry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gar",
        description="GAR workspace architecture reference CLI",
    )
    groups = parser.add_subparsers(dest="group", required=True)

    sim = groups.add_parser("sim")
    sim.add_argument("parts", nargs="+", metavar="{build|deploy|env}")
    sim.add_argument("--workspace", metavar="NAME")

    target = groups.add_parser("target")
    target.add_argument("action", choices=("build", "deploy"))
    target.add_argument("--workspace", metavar="NAME")

    return parser


def sim_command(parts: list[str]) -> GarCommand:
    if parts == ["build"]:
        return SIM_BUILD
    if parts == ["build", "clean"]:
        return SIM_CLEAN
    if parts == ["deploy"]:
        return SIM_DEPLOY
    if parts == ["env", "build"]:
        return SIM_RUNTIME_BUILD
    if parts == ["env", "deploy"]:
        return SIM_RUNTIME_DEPLOY
    raise GarDomainError(f"simulation commandは未対応です: {' '.join(parts)}")


def target_command(action: str) -> GarCommand:
    if action == "build":
        return TARGET_BUILD
    if action == "deploy":
        return TARGET_DEPLOY
    raise GarDomainError(f"target commandは未対応です: {action}")


def render_result(command: GarCommand, artifact: Artifact | None) -> None:
    if command == SIM_CLEAN:
        print("Simulation artifactを削除しました。")
    elif artifact is None:
        print("このsimulation environmentには個別のruntime artifactは不要です。")
    else:
        print(f"Artifact: {artifact.bundle_path}")


def main(argv: Sequence[str] | None = None) -> int:
    command_args = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(command_args)

    artifacts = LocalArtifactStore()
    workspaces = ConfigWorkspaceRegistry()
    build_environments = ConfigBuildEnvironmentResolver(artifacts)

    try:
        if args.group == "sim":
            services = SimulationCommandServices(
                workspaces=workspaces,
                build_environments=build_environments,
                artifacts=artifacts,
                simulation_environments=ConfigSimulationEnvironmentResolver(),
            )
            command = sim_command(args.parts)
            artifact = dispatch_sim_command(
                command,
                workspace_selector=args.workspace,
                services=services,
            )
            render_result(command, artifact)
            return 0

        if args.group == "target":
            services = TargetCommandServices(
                workspaces=workspaces,
                build_environments=build_environments,
                artifacts=artifacts,
                target_environments=ConfigTargetEnvironmentResolver(),
            )
            command = target_command(args.action)
            artifact = dispatch_target_command(
                command,
                workspace_selector=args.workspace,
                services=services,
            )
            render_result(command, artifact)
            return 0

    except AccessConnectionError as exc:
        workspace = workspaces.get(args.workspace)
        retry_command = shlex.join(("gar", *command_args))
        recovery = AccessRecoveryPlanner().plan(
            exc,
            workspace=workspace,
            retry_command=retry_command,
            purpose=args.group,
        )
        TerminalBridgeRecoveryExecutor(run_terminal_request).execute(recovery)
        print(f"gar: {exc}", file=sys.stderr)
        for instruction in recovery.instructions:
            print(f"  {instruction}", file=sys.stderr)
        return 1
    except GarDomainError as exc:
        print(f"gar: {exc}", file=sys.stderr)
        return 1

    return 1


def _main() -> NoReturn:
    raise SystemExit(main())


if __name__ == "__main__":
    _main()
