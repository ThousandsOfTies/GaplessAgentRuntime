"""Resolve simulation runtimes and compose them with access channels."""

from __future__ import annotations

from scripts.gar_lib.access.ssh import ScpFileChannel, SshCommandChannel
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.simulation.environment import DeployableSimulationEnvironment
from scripts.gar_lib.simulation.linux import LinuxSimCommandBuilder
from scripts.gar_lib.simulation.linux_systemd import LinuxSystemdSimulationEnvironment


class ConfigSimulationEnvironmentResolver:
    def for_workspace(self, workspace: Workspace) -> DeployableSimulationEnvironment:
        environment_id = workspace.selected_environments.get("simulator")
        if environment_id == "ssh_remote":
            host = workspace.ec2.get("host")
            if not isinstance(host, str) or not host:
                raise GarDomainError(f"simulation hostが未設定です: {workspace.name}")
            return LinuxSystemdSimulationEnvironment(
                command_channel=SshCommandChannel(host),
                file_channel=ScpFileChannel(host),
                command_builder=LinuxSimCommandBuilder(),
            )
        raise GarDomainError(f"simulation environmentはまだ未対応です: {environment_id or '(未設定)'}")
