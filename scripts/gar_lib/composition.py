"""Construct config-backed collaborators for the GAR application layer."""

from __future__ import annotations

from scripts.gar_lib.application import ApplicationServices
from scripts.gar_lib.artifacts.store import LocalArtifactStore
from scripts.gar_lib.build.resolver import ConfigBuildEnvironmentResolver
from scripts.gar_lib.hardware import CsvHardwareDefinitionRepository
from scripts.gar_lib.simulation.control_resolver import ConfigSimulationHardwareControlResolver
from scripts.gar_lib.simulation.host_resolver import ConfigSimulationHostControllerResolver
from scripts.gar_lib.simulation.resolver import ConfigSimulationEnvironmentResolver
from scripts.gar_lib.simulation.session import VsCodeSimulationSessionManager
from scripts.gar_lib.target.resolver import ConfigTargetEnvironmentResolver
from scripts.gar_lib.workspaces.registry import ConfigWorkspaceRegistry


def compose_application() -> ApplicationServices:
    artifacts = LocalArtifactStore()
    return ApplicationServices(
        workspaces=ConfigWorkspaceRegistry(),
        build_environments=ConfigBuildEnvironmentResolver(artifacts),
        artifacts=artifacts,
        simulation_environments=ConfigSimulationEnvironmentResolver(),
        simulation_hosts=ConfigSimulationHostControllerResolver(),
        simulation_hardware=ConfigSimulationHardwareControlResolver(),
        simulation_sessions=VsCodeSimulationSessionManager(),
        target_environments=ConfigTargetEnvironmentResolver(),
        hardware=CsvHardwareDefinitionRepository(),
    )
