"""Reference entry point for the new GAR architecture during migration.

Production ``cli.py`` now routes implemented commands through the same
orchestration services; this smaller entry point remains useful for inspection.
"""

from __future__ import annotations

import argparse
import sys
from typing import NoReturn

from scripts.gar_lib.artifacts.store import LocalArtifactStore
from scripts.gar_lib.build.resolver import ConfigBuildEnvironmentResolver
from scripts.gar_lib.commands.sim_next import SimCommandServices, dispatch
from scripts.gar_lib.commands.terminal import run_terminal_request
from scripts.gar_lib.core.command import SIM_BUILD, SIM_DEPLOY, SIM_RUNTIME_BUILD, SIM_RUNTIME_DEPLOY
from scripts.gar_lib.core.errors import AccessConnectionError, GarDomainError
from scripts.gar_lib.recovery.access import AccessRecoveryPlanner
from scripts.gar_lib.recovery.terminal import TerminalBridgeRecoveryExecutor
from scripts.gar_lib.simulation.resolver import ConfigSimulationEnvironmentResolver
from scripts.gar_lib.workspaces.registry import ConfigWorkspaceRegistry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gar-temp",
        description="GAR新アーキテクチャの並行実装入口",
    )
    groups = parser.add_subparsers(dest="group", required=True)
    sim = groups.add_parser("sim")
    sim.add_argument("parts", nargs="+", metavar="{build|deploy|env}")
    sim.add_argument("--workspace")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    artifacts = LocalArtifactStore()
    services = SimCommandServices(
        workspaces=ConfigWorkspaceRegistry(),
        build_environments=ConfigBuildEnvironmentResolver(artifacts),
        artifacts=artifacts,
        simulation_environments=ConfigSimulationEnvironmentResolver(),
    )

    try:
        command = None
        if args.parts == ["build"]:
            command = SIM_BUILD
        elif args.parts == ["deploy"]:
            command = SIM_DEPLOY
        elif args.parts == ["env", "build"]:
            command = SIM_RUNTIME_BUILD
        elif args.parts == ["env", "deploy"]:
            command = SIM_RUNTIME_DEPLOY
        if args.group == "sim" and command is not None:
            artifact = dispatch(
                command,
                workspace_selector=args.workspace,
                services=services,
            )
            if artifact is None:
                print("このsimulation environmentには個別のruntime artifactは不要です。")
            else:
                print(f"Artifact: {artifact.bundle_path}")
            return 0
    except AccessConnectionError as exc:
        workspace = services.workspaces.get(args.workspace)
        retry = "gar " + " ".join((args.group, *args.parts))
        if args.workspace:
            retry += f" --workspace {args.workspace}"
        action = AccessRecoveryPlanner().plan(exc, workspace=workspace, retry_command=retry)
        TerminalBridgeRecoveryExecutor(run_terminal_request).execute(action)
        print(f"gar-temp: {exc}", file=sys.stderr)
        for instruction in action.instructions:
            print(f"  {instruction}", file=sys.stderr)
        return 1
    except GarDomainError as exc:
        print(f"gar-temp: {exc}", file=sys.stderr)
        return 1

    return 1


def _main() -> NoReturn:
    raise SystemExit(main())


if __name__ == "__main__":
    _main()
