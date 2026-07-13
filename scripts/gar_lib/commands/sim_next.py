"""New simulation command orchestration, introduced alongside legacy sim.py."""

from __future__ import annotations

from dataclasses import dataclass

from scripts.gar_lib.artifacts.store import ArtifactStore
from scripts.gar_lib.build.resolver import BuildEnvironmentResolver
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.command import (
    SIM_BUILD,
    SIM_DEPLOY,
    SIM_RUNTIME_BUILD,
    SIM_RUNTIME_DEPLOY,
    GarCommand,
)
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.simulation.environment import SimulationEnvironmentResolver
from scripts.gar_lib.workspaces.registry import WorkspaceRegistry


@dataclass(frozen=True)
class SimCommandServices:
    workspaces: WorkspaceRegistry
    build_environments: BuildEnvironmentResolver
    artifacts: ArtifactStore
    simulation_environments: SimulationEnvironmentResolver


def dispatch(
    command: GarCommand,
    *,
    workspace_selector: str | None,
    services: SimCommandServices,
) -> Artifact | None:
    workspace = services.workspaces.get(workspace_selector)

    if command == SIM_BUILD:
        build_environment = services.build_environments.for_workspace(workspace)
        return build_environment.build(ArtifactKind.SIM_APP, workspace)

    if command == SIM_RUNTIME_BUILD:
        simulation_environment = services.simulation_environments.for_workspace(workspace)
        if not simulation_environment.requires_runtime_artifact:
            return None
        build_environment = services.build_environments.for_workspace(workspace)
        return build_environment.build(ArtifactKind.SIM_RUNTIME, workspace)

    if command == SIM_DEPLOY:
        artifact = services.artifacts.latest(ArtifactKind.SIM_APP, workspace)
        services.simulation_environments.for_workspace(workspace).deploy(artifact)
        return artifact

    if command == SIM_RUNTIME_DEPLOY:
        simulation_environment = services.simulation_environments.for_workspace(workspace)
        if not simulation_environment.requires_runtime_artifact:
            return None
        artifact = services.artifacts.latest(ArtifactKind.SIM_RUNTIME, workspace)
        simulation_environment.deploy(artifact)
        return artifact

    raise GarDomainError(f"新しい sim command 経路ではまだ未対応です: {command}")
