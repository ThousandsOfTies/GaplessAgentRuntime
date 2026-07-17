"""GAR use cases expressed as collaborations between domain-level objects."""

from __future__ import annotations

from dataclasses import dataclass

from scripts.gar_lib.artifacts.store import ArtifactStore
from scripts.gar_lib.build.base import BuildEnvironmentResolver
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.command import (
    SIM_BUILD,
    SIM_CLEAN,
    SIM_DEPLOY,
    SIM_HOST_START,
    SIM_HOST_STATUS,
    SIM_HOST_STOP,
    SIM_RUNTIME_BUILD,
    SIM_RUNTIME_DEPLOY,
    SIM_RUNTIME_DIAG,
    SIM_RUNTIME_LOG,
    SIM_RUNTIME_START,
    SIM_RUNTIME_STATUS,
    SIM_RUNTIME_STOP,
    TARGET_BUILD,
    TARGET_DEPLOY,
    GarCommand,
)
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.hardware import HardwareDefinitionRepository
from scripts.gar_lib.simulation.control import (
    HardwareControlResult,
    SimulationHardwareControlResolver,
)
from scripts.gar_lib.simulation.diagnostic import SimulationDiagnosticReport
from scripts.gar_lib.simulation.environment import SimulationEnvironmentResolver
from scripts.gar_lib.simulation.host import (
    SimulationHostControllerResolver,
    SimulationHostStartResult,
    SimulationHostState,
)
from scripts.gar_lib.simulation.session import SimulationSessionManager
from scripts.gar_lib.target.environment import TargetEnvironmentResolver
from scripts.gar_lib.workspaces.registry import WorkspaceRegistry


@dataclass(frozen=True)
class ApplicationServices:
    workspaces: WorkspaceRegistry
    build_environments: BuildEnvironmentResolver
    artifacts: ArtifactStore
    simulation_environments: SimulationEnvironmentResolver
    simulation_hosts: SimulationHostControllerResolver
    simulation_hardware: SimulationHardwareControlResolver
    simulation_sessions: SimulationSessionManager
    target_environments: TargetEnvironmentResolver
    hardware: HardwareDefinitionRepository


@dataclass(frozen=True)
class CommandOutcome:
    workspace: Workspace
    exit_code: int = 0
    artifact: Artifact | None = None
    host_start: SimulationHostStartResult | None = None
    host_state: SimulationHostState | None = None
    diagnostic: SimulationDiagnosticReport | None = None
    hardware: HardwareControlResult | None = None


def dispatch(
    command: GarCommand,
    *,
    workspace_selector: str | None,
    services: ApplicationServices,
    update_address: bool = True,
    update_repository: bool = False,
    manage_session: bool = True,
    settings: str | None = None,
    profile_name: str | None = None,
    params: dict[str, object] | None = None,
) -> CommandOutcome:
    workspace = services.workspaces.get(workspace_selector)

    if command == TARGET_BUILD:
        build_environment = services.build_environments.for_workspace(workspace)
        artifact = build_environment.build(ArtifactKind.TARGET_APP, workspace)
        return CommandOutcome(workspace, artifact=artifact)

    if command == TARGET_DEPLOY:
        artifact = services.artifacts.latest(ArtifactKind.TARGET_APP, workspace)
        target_environment = services.target_environments.for_workspace(workspace)
        target_environment.deploy(artifact)
        return CommandOutcome(workspace, artifact=artifact)

    if command == SIM_BUILD:
        build_environment = services.build_environments.for_workspace(workspace)
        artifact = build_environment.build(ArtifactKind.SIM_APP, workspace)
        return CommandOutcome(workspace, artifact=artifact)

    if command == SIM_CLEAN:
        build_environment = services.build_environments.for_workspace(workspace)
        build_environment.clean(ArtifactKind.SIM_APP, workspace)
        return CommandOutcome(workspace)

    if command == SIM_DEPLOY:
        artifact = services.artifacts.latest(ArtifactKind.SIM_APP, workspace)
        simulation_environment = services.simulation_environments.for_workspace(workspace)
        simulation_environment.deploy(artifact)
        return CommandOutcome(workspace, artifact=artifact)

    if command == SIM_RUNTIME_BUILD:
        simulation_environment = services.simulation_environments.for_workspace(workspace)
        if not simulation_environment.requires_runtime_artifact:
            return CommandOutcome(workspace)
        build_environment = services.build_environments.for_workspace(workspace)
        artifact = build_environment.build(ArtifactKind.SIM_RUNTIME, workspace)
        return CommandOutcome(workspace, artifact=artifact)

    if command == SIM_RUNTIME_DEPLOY:
        simulation_environment = services.simulation_environments.for_workspace(workspace)
        if not simulation_environment.requires_runtime_artifact:
            return CommandOutcome(workspace)
        artifact = services.artifacts.latest(ArtifactKind.SIM_RUNTIME, workspace)
        simulation_environment.deploy(artifact)
        return CommandOutcome(workspace, artifact=artifact)

    if command == SIM_HOST_START:
        simulation_host = services.simulation_hosts.for_workspace(workspace)
        result = simulation_host.start(
            update_address=update_address,
            update_repository=update_repository,
        )
        return CommandOutcome(workspace, host_start=result)

    if command == SIM_HOST_STOP:
        simulation_host = services.simulation_hosts.for_workspace(workspace)
        simulation_host.stop()
        return CommandOutcome(workspace)

    if command == SIM_HOST_STATUS:
        simulation_host = services.simulation_hosts.for_workspace(workspace)
        return CommandOutcome(workspace, host_state=simulation_host.status())

    if command in {SIM_RUNTIME_START, SIM_RUNTIME_STOP, SIM_RUNTIME_STATUS}:
        simulation_environment = services.simulation_environments.for_workspace(workspace)
        hardware = services.hardware.load()
        host = simulation_environment.runtime_host

        if command == SIM_RUNTIME_START:
            exit_code = simulation_environment.start(hardware)
            if exit_code == 0 and host is not None:
                services.simulation_sessions.configure_terminal(
                    host,
                    settings=settings,
                    profile_name=profile_name,
                )
                if manage_session:
                    exit_code = services.simulation_sessions.start(host)
            return CommandOutcome(workspace, exit_code=exit_code)

        if command == SIM_RUNTIME_STOP:
            exit_code = simulation_environment.stop(hardware)
            if exit_code == 0 and manage_session and host is not None:
                exit_code = services.simulation_sessions.stop(host)
            return CommandOutcome(workspace, exit_code=exit_code)

        session_exit = services.simulation_sessions.status(host) if host is not None else 0
        runtime_exit = simulation_environment.status(hardware)
        return CommandOutcome(workspace, exit_code=session_exit or runtime_exit)

    if command == SIM_RUNTIME_LOG:
        simulation_environment = services.simulation_environments.for_workspace(workspace)
        return CommandOutcome(workspace, exit_code=simulation_environment.log())

    if command == SIM_RUNTIME_DIAG:
        simulation_environment = services.simulation_environments.for_workspace(workspace)
        diagnostic = simulation_environment.diag(services.hardware.load())
        return CommandOutcome(workspace, exit_code=diagnostic.exit_code, diagnostic=diagnostic)

    if command.group == "sim" and command.subject == "gpio":
        simulation_hardware = services.simulation_hardware.for_workspace(workspace)
        result = simulation_hardware.gpio(command.action, services.hardware.load())
        return CommandOutcome(workspace, exit_code=result.exit_code, hardware=result)

    if command.group == "sim" and command.subject == "panel":
        simulation_hardware = services.simulation_hardware.for_workspace(workspace)
        result = simulation_hardware.panel(command.action, params or {})
        return CommandOutcome(workspace, exit_code=result.exit_code, hardware=result)

    raise GarDomainError(f"commandは未対応です: {command}")
