"""Resolve simulation runtimes and compose them with access channels."""

from __future__ import annotations

import os
from pathlib import Path

from scripts.gar_lib.access.aws import AwsCliChannel
from scripts.gar_lib.access.local import LocalProcessChannel
from scripts.gar_lib.access.ssh import ScpFileChannel, SshCommandChannel
from scripts.gar_lib.config import PROJECT_ROOT
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.simulation.aws_ssm import AwsSsmSimulationEnvironment
from scripts.gar_lib.simulation.environment import SimulationEnvironment
from scripts.gar_lib.simulation.esp32_qemu import Esp32QemuSimulationEnvironment
from scripts.gar_lib.simulation.linux import LinuxSystemdCommandBuilder
from scripts.gar_lib.simulation.linux_systemd import LinuxSystemdSimulationEnvironment
from scripts.gar_lib.simulation.mujoco import MujocoSimulationEnvironment
from scripts.gar_lib.simulation.renode import RenodeSimulationEnvironment
from scripts.gar_lib.simulation.wokwi import WokwiSimulationEnvironment


class ConfigSimulationEnvironmentResolver:
    def for_workspace(self, workspace: Workspace) -> SimulationEnvironment:
        environment_id = workspace.selected_environments.get("simulator")
        if environment_id == "ssh_remote":
            host = workspace.ec2.get("host")
            if not isinstance(host, str) or not host:
                raise GarDomainError(f"simulation hostが未設定です: {workspace.name}")
            return LinuxSystemdSimulationEnvironment(
                command_channel=SshCommandChannel(host),
                file_channel=ScpFileChannel(host),
                command_builder=LinuxSystemdCommandBuilder(),
                runtime_host=host,
            )
        if environment_id == "wokwi":
            configured = os.environ.get("GAR_WOKWI_PROJECT_DIR")
            if configured:
                project_dir = Path(configured).expanduser().resolve()
            elif workspace.connection_type == "local":
                project_dir = workspace.local_root / ".gar" / "wokwi" / "m5stackc"
            else:
                project_dir = PROJECT_ROOT / ".gar" / "wokwi" / workspace.id
            return WokwiSimulationEnvironment(project_dir, LocalProcessChannel())
        if environment_id == "mujoco":
            return MujocoSimulationEnvironment(process_channel=LocalProcessChannel())
        if environment_id == "renode_mcu":
            return RenodeSimulationEnvironment(process_channel=LocalProcessChannel())
        if environment_id == "esp32_qemu_firmware":
            return Esp32QemuSimulationEnvironment(process_channel=LocalProcessChannel())
        if environment_id == "aws_ssm":
            instance_id = workspace.ec2.get("instance_id")
            region = workspace.ec2.get("region")
            missing = [
                name
                for name, value in (("instance_id", instance_id), ("region", region))
                if not isinstance(value, str) or not value
            ]
            if missing:
                raise GarDomainError(
                    f"AWS SSM設定が不足しています ({', '.join(missing)}): {workspace.name}"
                )
            return AwsSsmSimulationEnvironment(
                aws=AwsCliChannel(region),
                instance_id=instance_id,
            )
        raise GarDomainError(f"simulation environmentはまだ未対応です: {environment_id or '(未設定)'}")
