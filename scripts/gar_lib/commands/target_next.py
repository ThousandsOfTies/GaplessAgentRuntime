"""Target command orchestration using build, artifact, and target environments."""

from __future__ import annotations

from dataclasses import dataclass

from scripts.gar_lib.artifacts.store import ArtifactStore
from scripts.gar_lib.build.resolver import BuildEnvironmentResolver
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.command import TARGET_BUILD, TARGET_DEPLOY, GarCommand
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.target.environment import TargetEnvironmentResolver
from scripts.gar_lib.workspaces.registry import WorkspaceRegistry


@dataclass(frozen=True)
class TargetCommandServices:
    workspaces: WorkspaceRegistry
    build_environments: BuildEnvironmentResolver
    artifacts: ArtifactStore
    target_environments: TargetEnvironmentResolver


def dispatch(
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

    raise GarDomainError(f"新しい target command 経路では未対応です: {command}")
