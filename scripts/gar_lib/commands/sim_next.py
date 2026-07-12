"""New simulation command orchestration, introduced alongside legacy sim.py."""

from __future__ import annotations

from dataclasses import dataclass

from scripts.gar_lib.artifacts.store import ArtifactStore
from scripts.gar_lib.build.resolver import BuildEnvironmentResolver
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.command import SIM_BUILD, GarCommand
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.workspaces.registry import WorkspaceRegistry


@dataclass(frozen=True)
class SimCommandServices:
    workspaces: WorkspaceRegistry
    build_environments: BuildEnvironmentResolver
    artifacts: ArtifactStore


def dispatch(
    command: GarCommand,
    *,
    workspace_selector: str | None,
    services: SimCommandServices,
) -> Artifact:
    workspace = services.workspaces.get(workspace_selector)

    if command == SIM_BUILD:
        build_environment = services.build_environments.for_workspace(workspace)
        return build_environment.build(ArtifactKind.SIM_APP, workspace)

    raise GarDomainError(f"新しい sim command 経路ではまだ未対応です: {command}")
