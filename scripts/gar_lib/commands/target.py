"""Application service and CLI entry point for ``gar target`` commands."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from scripts.gar_lib.artifacts.store import ArtifactStore, LocalArtifactStore
from scripts.gar_lib.build.resolver import BuildEnvironmentResolver, ConfigBuildEnvironmentResolver
from scripts.gar_lib.commands.terminal import run_terminal_request
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.command import TARGET_BUILD, TARGET_DEPLOY, GarCommand
from scripts.gar_lib.core.errors import AccessConnectionError, GarDomainError
from scripts.gar_lib.recovery.access import AccessRecoveryPlanner
from scripts.gar_lib.recovery.terminal import TerminalBridgeRecoveryExecutor
from scripts.gar_lib.target.environment import TargetEnvironmentResolver
from scripts.gar_lib.target.resolver import ConfigTargetEnvironmentResolver
from scripts.gar_lib.workspaces.registry import ConfigWorkspaceRegistry, WorkspaceRegistry


@dataclass(frozen=True)
class TargetCommandServices:
    workspaces: WorkspaceRegistry
    build_environments: BuildEnvironmentResolver
    artifacts: ArtifactStore
    target_environments: TargetEnvironmentResolver


def dispatch_target_command(
    command: GarCommand,
    *,
    workspace_selector: str | None,
    services: TargetCommandServices,
) -> Artifact:
    workspace = services.workspaces.get(workspace_selector)

    if command == TARGET_BUILD:
        build_environment = services.build_environments.for_workspace(workspace)
        return build_environment.build(ArtifactKind.TARGET_APP, workspace)

    if command == TARGET_DEPLOY:
        artifact = services.artifacts.latest(ArtifactKind.TARGET_APP, workspace)
        services.target_environments.for_workspace(workspace).deploy(artifact)
        return artifact

    raise GarDomainError(f"target command は未対応です: {command}")


def run_target_command(
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
        artifact = dispatch_target_command(
            command,
            workspace_selector=workspace_selector,
            services=services,
        )
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
