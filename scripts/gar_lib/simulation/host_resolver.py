"""Resolve simulation host controllers from workspace configuration."""

from __future__ import annotations

from scripts.gar_lib.access.aws import AwsCliChannel
from scripts.gar_lib.access.ssh import SshCommandChannel
from scripts.gar_lib.access.ssh_config import SshConfigHostAddressUpdater
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.simulation.aws_ec2 import AwsEc2SimulationHostController
from scripts.gar_lib.simulation.host import SimulationHostController


class ConfigSimulationHostControllerResolver:
    def for_workspace(self, workspace: Workspace) -> SimulationHostController:
        instance_id = workspace.ec2.get("instance_id")
        region = workspace.ec2.get("region")
        host = workspace.ec2.get("host")
        missing = [
            name
            for name, value in (("host", host), ("instance_id", instance_id), ("region", region))
            if not isinstance(value, str) or not value
        ]
        if missing:
            raise GarDomainError(
                f"simulation host設定が不足しています ({', '.join(missing)}): {workspace.name}"
            )

        repository_path = workspace.ec2.get("repo_dir")
        return AwsEc2SimulationHostController(
            host=host,
            instance_id=instance_id,
            region=region,
            aws=AwsCliChannel(region),
            address_updater=SshConfigHostAddressUpdater(),
            repository_channel=SshCommandChannel(host),
            repository_path=repository_path if isinstance(repository_path, str) else None,
        )
