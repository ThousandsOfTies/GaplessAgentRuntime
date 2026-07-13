"""Resolve hardware control-plane capabilities for a workspace."""

from __future__ import annotations

from scripts.gar_lib.access.ssh import SshCommandChannel
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.simulation.control import (
    LinuxBridgeHardwareControl,
    SimulationHardwareControl,
)
from scripts.gar_lib.simulation.linux import LinuxSystemdCommandBuilder
from scripts.gar_lib.simulation.mujoco import MujocoBridgeHardwareControl


class ConfigSimulationHardwareControlResolver:
    def for_workspace(self, workspace: Workspace) -> SimulationHardwareControl:
        environment_id = workspace.selected_environments.get("simulator")
        if environment_id == "ssh_remote":
            host = workspace.ec2.get("host")
            if not isinstance(host, str) or not host:
                raise GarDomainError(f"simulation hostが未設定です: {workspace.name}")
            return LinuxBridgeHardwareControl(
                SshCommandChannel(host),
                LinuxSystemdCommandBuilder(),
                host=host,
            )
        if environment_id == "mujoco":
            return MujocoBridgeHardwareControl()
        raise GarDomainError(
            f"hardware controlはこのsimulation environmentに未対応です: {environment_id or '(未設定)'}"
        )
