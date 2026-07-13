"""Production-facing entry for target command orchestration."""

from __future__ import annotations

import sys

from scripts.gar_lib.artifacts.store import LocalArtifactStore
from scripts.gar_lib.build.resolver import ConfigBuildEnvironmentResolver
from scripts.gar_lib.commands.target_next import TargetCommandServices, dispatch
from scripts.gar_lib.commands.terminal import run_terminal_request
from scripts.gar_lib.core.command import GarCommand
from scripts.gar_lib.core.errors import AccessConnectionError, GarDomainError
from scripts.gar_lib.recovery.access import AccessRecoveryPlanner
from scripts.gar_lib.recovery.terminal import TerminalBridgeRecoveryExecutor
from scripts.gar_lib.target.resolver import ConfigTargetEnvironmentResolver
from scripts.gar_lib.workspaces.registry import ConfigWorkspaceRegistry


def run_next_target_command(
    command: GarCommand,
    *,
    workspace_selector: str | None,
    retry_command: str,
) -> int:
    artifacts = LocalArtifactStore()
    services = TargetCommandServices(
        workspaces=ConfigWorkspaceRegistry(),
        build_environments=ConfigBuildEnvironmentResolver(artifacts),
        artifacts=artifacts,
        target_environments=ConfigTargetEnvironmentResolver(),
    )
    try:
        artifact = dispatch(command, workspace_selector=workspace_selector, services=services)
        print(f"Artifact: {artifact.bundle_path}")
        return 0
    except AccessConnectionError as exc:
        workspace = services.workspaces.get(workspace_selector)
        recovery = AccessRecoveryPlanner().plan(
            exc,
            workspace=workspace,
            retry_command=retry_command,
            purpose="target",
        )
        TerminalBridgeRecoveryExecutor(run_terminal_request).execute(recovery)
        print(f"gar: {exc}", file=sys.stderr)
        for instruction in recovery.instructions:
            print(f"  {instruction}", file=sys.stderr)
        return 1
    except GarDomainError as exc:
        print(f"gar: {exc}", file=sys.stderr)
        return 1
