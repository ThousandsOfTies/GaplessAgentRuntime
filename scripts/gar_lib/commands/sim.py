"""Application service and CLI entry points for ``gar sim`` commands."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass

from scripts.gar_lib.artifacts.store import ArtifactStore, LocalArtifactStore
from scripts.gar_lib.build.resolver import BuildEnvironmentResolver, ConfigBuildEnvironmentResolver
from scripts.gar_lib.commands.hw import load_hw_definition
from scripts.gar_lib.commands.terminal import run_terminal_request
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.command import (
    SIM_BUILD,
    SIM_CLEAN,
    SIM_DEPLOY,
    SIM_RUNTIME_BUILD,
    SIM_RUNTIME_DEPLOY,
    GarCommand,
)
from scripts.gar_lib.core.errors import AccessConnectionError, GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.recovery.access import AccessRecoveryPlanner
from scripts.gar_lib.recovery.terminal import TerminalBridgeRecoveryExecutor
from scripts.gar_lib.simulation.control_resolver import ConfigSimulationHardwareControlResolver
from scripts.gar_lib.simulation.environment import (
    SimulationEnvironmentResolver,
)
from scripts.gar_lib.simulation.host_resolver import ConfigSimulationHostControllerResolver
from scripts.gar_lib.simulation.remote_session import (
    start_sim_port_forward,
    status_sim_port_forward,
    stop_sim_port_forward,
    write_sim_terminal_profile,
)
from scripts.gar_lib.simulation.resolver import ConfigSimulationEnvironmentResolver
from scripts.gar_lib.workspaces.registry import ConfigWorkspaceRegistry, WorkspaceRegistry


@dataclass(frozen=True)
class SimulationCommandServices:
    workspaces: WorkspaceRegistry
    build_environments: BuildEnvironmentResolver
    artifacts: ArtifactStore
    simulation_environments: SimulationEnvironmentResolver


def dispatch_sim_command(
    command: GarCommand,
    *,
    workspace_selector: str | None,
    services: SimulationCommandServices,
) -> Artifact | None:
    """Execute the build/deploy use case expressed by *command*."""

    workspace = services.workspaces.get(workspace_selector)

    if command == SIM_BUILD:
        build_environment = services.build_environments.for_workspace(workspace)
        return build_environment.build(ArtifactKind.SIM_APP, workspace)

    if command == SIM_CLEAN:
        build_environment = services.build_environments.for_workspace(workspace)
        build_environment.clean(ArtifactKind.SIM_APP, workspace)
        return None

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

    raise GarDomainError(f"simulation command は未対応です: {command}")


def _recover_access(
    error: AccessConnectionError,
    *,
    workspace: Workspace,
    retry_command: str,
) -> int:
    recovery = AccessRecoveryPlanner().plan(error, workspace=workspace, retry_command=retry_command)
    TerminalBridgeRecoveryExecutor(run_terminal_request).execute(recovery)
    print(f"gar: {error}", file=sys.stderr)
    for instruction in recovery.instructions:
        print(f"  {instruction}", file=sys.stderr)
    return 1


def run_sim_host_command(
    action_name: str,
    *,
    workspace_selector: str | None,
    retry_command: str,
    update_address: bool = True,
    update_repository: bool = False,
    json_output: bool = False,
) -> int:
    workspaces = ConfigWorkspaceRegistry()
    try:
        workspace = workspaces.get(workspace_selector)
        controller = ConfigSimulationHostControllerResolver().for_workspace(workspace)
        if action_name == "start":
            print(f"gar sim host: {workspace.name} の起動を要求し、runningになるまで待機します...")
            result = controller.start(
                update_address=update_address,
                update_repository=update_repository,
            )
            print(f"gar sim host: running. public ip = {result.state.public_ip}")
            if update_address:
                if result.address_updated:
                    print(
                        f"gar sim host: SSH config の Host {result.state.host} を "
                        f"{result.state.public_ip} に更新しました。"
                    )
                else:
                    print(
                        f"gar sim host: SSH config の Host {result.state.host} を更新できませんでした。",
                        file=sys.stderr,
                    )
            if result.repository_updated:
                print("gar sim host: simulation hostのrepositoryを更新しました。")
            if result.repository_update_skipped:
                print(
                    "gar sim host: --pullが指定されましたがec2.repo_dirが未設定のため、"
                    "git pullをスキップしました。",
                    file=sys.stderr,
                )
            return 0
        if action_name == "stop":
            controller.stop()
            print(f"gar sim host: shutdown要求を送信しました ({workspace.ec2['instance_id']})")
            return 0
        if action_name == "status":
            state = controller.status()
            if json_output:
                print(json.dumps(state.to_payload(), ensure_ascii=False, indent=2))
            else:
                print(f"instance : {state.instance_id}")
                print(f"region   : {state.region}")
                print(f"state    : {state.state}")
                print(f"public ip: {state.public_ip or '(none)'}")
            return 0
        raise GarDomainError(f"simulation host操作は未対応です: {action_name}")
    except AccessConnectionError as exc:
        workspace = workspaces.get(workspace_selector)
        return _recover_access(exc, workspace=workspace, retry_command=retry_command)
    except GarDomainError as exc:
        print(f"gar: {exc}", file=sys.stderr)
        return 1


def run_sim_diagnostic(
    *,
    workspace_selector: str | None,
    retry_command: str,
    json_output: bool,
) -> int:
    workspaces = ConfigWorkspaceRegistry()
    try:
        workspace = workspaces.get(workspace_selector)
        environment = ConfigSimulationEnvironmentResolver().for_workspace(workspace)
        diagnostic = environment.diag(load_hw_definition())
        host = workspace.ec2.get("host")
        payload = diagnostic.to_payload(host=host if isinstance(host, str) else None)
        if json_output:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            _print_diagnostic(payload)
        return diagnostic.exit_code
    except AccessConnectionError as exc:
        workspace = workspaces.get(workspace_selector)
        return _recover_access(exc, workspace=workspace, retry_command=retry_command)
    except GarDomainError as exc:
        print(f"gar: {exc}", file=sys.stderr)
        return 1


def _print_diagnostic(payload: dict[str, object]) -> None:
    print(f"status: {'ok' if payload.get('ok') is True else 'error'}")
    if payload.get("host"):
        print(f"host: {payload['host']}")
    if payload.get("error"):
        print(f"error: {payload['error']}")
    processes = payload.get("processes")
    if isinstance(processes, list):
        print(f"processes: {len(processes)}")
        for process in processes:
            if isinstance(process, dict):
                print(f"  {process.get('pid', '?')}: {process.get('cmd', '')}")
    devices = payload.get("devices")
    if isinstance(devices, dict):
        print("devices:")
        for path, available in devices.items():
            print(f"  {path}: {'OK' if available else 'missing'}")
    if payload.get("api") is not None:
        print("api:")
        print(json.dumps(payload["api"], ensure_ascii=False, indent=2))


def run_sim_command(
    command: GarCommand,
    *,
    workspace_selector: str | None,
    retry_command: str,
) -> int:
    artifacts = LocalArtifactStore()
    services = SimulationCommandServices(
        workspaces=ConfigWorkspaceRegistry(),
        build_environments=ConfigBuildEnvironmentResolver(artifacts),
        artifacts=artifacts,
        simulation_environments=ConfigSimulationEnvironmentResolver(),
    )
    try:
        artifact = dispatch_sim_command(
            command,
            workspace_selector=workspace_selector,
            services=services,
        )
        if command == SIM_CLEAN:
            print("Simulation artifactを削除しました。")
        elif artifact is None:
            print("このsimulation environmentには個別のruntime artifactは不要です。")
        else:
            print(f"Artifact: {artifact.bundle_path}")
        return 0
    except AccessConnectionError as exc:
        workspace = services.workspaces.get(workspace_selector)
        return _recover_access(exc, workspace=workspace, retry_command=retry_command)
    except GarDomainError as exc:
        print(f"gar: {exc}", file=sys.stderr)
        return 1


def run_sim_lifecycle(
    action_name: str,
    *,
    workspace_selector: str | None,
    retry_command: str,
    settings: str | None = None,
    profile_name: str | None = None,
    manage_port_forward: bool = True,
) -> int:
    workspaces = ConfigWorkspaceRegistry()
    try:
        workspace = workspaces.get(workspace_selector)
        environment = ConfigSimulationEnvironmentResolver().for_workspace(workspace)
        hardware = load_hw_definition()
        host = environment.runtime_host
        if action_name == "start":
            result = environment.start(hardware)
            if result == 0 and host is not None:
                write_sim_terminal_profile(host=host, settings=settings, profile_name=profile_name)
                if manage_port_forward:
                    result = start_sim_port_forward(host)
            return result
        if action_name == "stop":
            result = environment.stop(hardware)
            if result == 0 and manage_port_forward and host is not None:
                result = stop_sim_port_forward(host)
            return result
        if action_name == "status":
            forward_result = status_sim_port_forward(host) if host is not None else 0
            runtime_result = environment.status(hardware)
            return forward_result or runtime_result
        if action_name == "log":
            return environment.log()
        raise GarDomainError(f"simulation lifecycle操作は未対応です: {action_name}")
    except AccessConnectionError as exc:
        workspace = workspaces.get(workspace_selector)
        return _recover_access(exc, workspace=workspace, retry_command=retry_command)
    except GarDomainError as exc:
        print(f"gar: {exc}", file=sys.stderr)
        return 1


def run_sim_hardware_command(
    action_name: str,
    *,
    workspace_selector: str | None,
    retry_command: str,
    json_output: bool = False,
) -> int:
    workspaces = ConfigWorkspaceRegistry()
    try:
        workspace = workspaces.get(workspace_selector)
        control = ConfigSimulationHardwareControlResolver().for_workspace(workspace)
        result = control.gpio(action_name, load_hw_definition())
        result.render(json_output=json_output)
        return result.exit_code
    except AccessConnectionError as exc:
        workspace = workspaces.get(workspace_selector)
        return _recover_access(exc, workspace=workspace, retry_command=retry_command)
    except GarDomainError as exc:
        print(f"gar: {exc}", file=sys.stderr)
        return 1


def run_sim_panel(
    action_name: str,
    *,
    workspace_selector: str | None,
    retry_command: str,
    json_output: bool = False,
    params: dict[str, object] | None = None,
) -> int:
    workspaces = ConfigWorkspaceRegistry()
    try:
        workspace = workspaces.get(workspace_selector)
        control = ConfigSimulationHardwareControlResolver().for_workspace(workspace)
        result = control.panel(action_name, params or {})
        result.render(json_output=json_output)
        return result.exit_code
    except AccessConnectionError as exc:
        workspace = workspaces.get(workspace_selector)
        return _recover_access(exc, workspace=workspace, retry_command=retry_command)
    except GarDomainError as exc:
        print(f"gar: {exc}", file=sys.stderr)
        return 1
