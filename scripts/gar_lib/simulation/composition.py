"""Compose simulation runtime objects from the environment selected by a workspace.

`gar config` で選ばれた backend id（または既存workspaceで明示された
`local_docker` / `wokwi` など）を見て、対応する実装とアクセス経路を組み立てるだけの層。
実処理は各実装が持つ。
"""

from __future__ import annotations

import os
from pathlib import Path

from scripts.gar_lib.access.aws import AwsCliChannel
from scripts.gar_lib.access.docker import (
    DockerCliChannel,
    DockerCommandChannel,
    DockerFileChannel,
)
from scripts.gar_lib.access.ssh import ScpFileChannel, SshCommandChannel
from scripts.gar_lib.access.virtualbox import VirtualBoxCliChannel
from scripts.gar_lib.core.config import PROJECT_ROOT
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.tools_repository import gar_tools_root
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.core.workspace_settings import DockerSettings
from scripts.gar_lib.simulation.hardware.control import (
    LinuxBridgeHardwareControl,
    SimulationHardwareControl,
)
from scripts.gar_lib.simulation.hardware.mujoco import MujocoBridgeHardwareControl
from scripts.gar_lib.simulation.host.aws_ec2 import AwsEc2SimulationHostController
from scripts.gar_lib.simulation.host.contract import SimulationHostController
from scripts.gar_lib.simulation.host.docker import (
    BACKEND_ID,
    DEFAULT_CONTAINER,
    DockerSimulationHostController,
)
from scripts.gar_lib.simulation.host.docker_spec import DockerHostSpec, docker_host_spec
from scripts.gar_lib.simulation.host.ssh_config import SshConfigHostAddressUpdater
from scripts.gar_lib.simulation.host.virtualbox import VirtualBoxSimulationHostController
from scripts.gar_lib.simulation.runtime.aws_ssm import AwsSsmSimulationEnvironment
from scripts.gar_lib.simulation.runtime.contract import SimulationEnvironment
from scripts.gar_lib.simulation.runtime.esp32_qemu import Esp32QemuSimulationEnvironment
from scripts.gar_lib.simulation.runtime.linux_commands import LinuxSystemdCommandBuilder
from scripts.gar_lib.simulation.runtime.linux_systemd import LinuxSystemdSimulationEnvironment
from scripts.gar_lib.simulation.runtime.mujoco import MujocoSimulationEnvironment
from scripts.gar_lib.simulation.runtime.process import LocalProcessChannel
from scripts.gar_lib.simulation.runtime.renode import RenodeSimulationEnvironment
from scripts.gar_lib.simulation.runtime.wokwi import WokwiSimulationEnvironment
from scripts.gar_lib.target.manifest import discover_target_manifests, target_by_id

LOCAL_DOCKER = "local_docker"
SSH_HOST_SIMULATORS = ("ssh_remote", "aws_ssm")
HOSTLESS_SIMULATORS = ("wokwi", "mujoco", "renode_mcu", "esp32_qemu_firmware", "product_hook")
AWS_EC2_HOST = "aws_ec2"
VIRTUALBOX_HOST = "virtualbox"


def selected_simulator(workspace: Workspace) -> str | None:
    return workspace.selected_environments.simulator


def simulation_environment_for(workspace: Workspace) -> SimulationEnvironment:
    """simulation runtime（stub / bridge）を操作するオブジェクトを作る。"""

    backend = selected_simulator(workspace)

    if backend == 'product_hook':
        from scripts.gar_lib.simulation.runtime.product_hook import ProductSimulatorHook
        return ProductSimulatorHook(workspace)

    if backend == LOCAL_DOCKER:
        container = _container_name(workspace)
        return LinuxSystemdSimulationEnvironment(
            command_channel=DockerCommandChannel(container),
            file_channel=DockerFileChannel(container),
            command_builder=LinuxSystemdCommandBuilder(),
        )

    if backend == "ssh_remote":
        host = _simulation_ssh_host(workspace)
        return LinuxSystemdSimulationEnvironment(
            command_channel=SshCommandChannel(host),
            file_channel=ScpFileChannel(host),
            command_builder=LinuxSystemdCommandBuilder(),
            session_host=host,
        )

    if backend == "wokwi":
        return WokwiSimulationEnvironment(_wokwi_project_dir(workspace), LocalProcessChannel())

    if backend == "mujoco":
        return MujocoSimulationEnvironment(process_channel=LocalProcessChannel())

    if backend == "renode_mcu":
        return RenodeSimulationEnvironment(process_channel=LocalProcessChannel())

    if backend == "esp32_qemu_firmware":
        return Esp32QemuSimulationEnvironment(process_channel=LocalProcessChannel())

    if backend == "aws_ssm":
        instance_id, region = _ssm_settings(workspace)
        return AwsSsmSimulationEnvironment(aws=AwsCliChannel(region), instance_id=instance_id)

    raise GarDomainError(f"simulation environmentはまだ未対応です: {backend or '(未設定)'}")


def simulation_host_for(workspace: Workspace) -> SimulationHostController:
    """Create the selected VirtualBox, AWS, or legacy Docker simulation host."""

    backend = selected_simulator(workspace)

    if backend == LOCAL_DOCKER:
        settings = workspace.docker
        container = _container_name(workspace)
        repository_path = settings.repo_dir
        return DockerSimulationHostController(
            container=container,
            spec=docker_spec_for(settings, target_id=workspace.selected_target),
            docker=DockerCliChannel(),
            repository_channel=DockerCommandChannel(container),
            repository_path=repository_path,
        )

    if backend in HOSTLESS_SIMULATORS:
        raise GarDomainError(f"{backend} simulation environmentには操作対象のsimulation hostがありません")
    if backend not in SSH_HOST_SIMULATORS:
        raise GarDomainError(f"simulation hostはこのsimulation environmentに未対応です: " f"{backend or '(未設定)'}")

    provider = _simulation_host_provider(workspace)
    host = _simulation_ssh_host(workspace)
    repository_path = workspace.simulation_repository_dir
    if provider == VIRTUALBOX_HOST:
        vm = workspace.virtualbox.vm
        if not vm:
            raise GarDomainError(f"VirtualBox VM名が未設定です: {workspace.name}")
        return VirtualBoxSimulationHostController(
            vm=vm,
            host=host,
            virtualbox=VirtualBoxCliChannel(),
            repository_channel=SshCommandChannel(host),
            repository_path=repository_path,
        )
    if provider != AWS_EC2_HOST:
        raise GarDomainError(f"simulation host providerは未対応です: {provider}")

    instance_id = workspace.ec2.instance_id
    region = workspace.ec2.region
    missing = [
        name
        for name, value in (("instance_id", instance_id), ("region", region))
        if not isinstance(value, str) or not value
    ]
    if missing:
        raise GarDomainError(f"simulation host設定が不足しています ({', '.join(missing)}): {workspace.name}")

    return AwsEc2SimulationHostController(
        host=host,
        instance_id=instance_id,
        region=region,
        aws=AwsCliChannel(region),
        address_updater=SshConfigHostAddressUpdater(),
        repository_channel=SshCommandChannel(host),
        repository_path=repository_path,
    )


def hardware_control_for(workspace: Workspace) -> SimulationHardwareControl:
    """virtual H/W を操作する control plane のオブジェクトを作る。"""

    backend = selected_simulator(workspace)

    if backend == LOCAL_DOCKER:
        container = _container_name(workspace)
        return LinuxBridgeHardwareControl(
            DockerCommandChannel(container),
            LinuxSystemdCommandBuilder(),
            host=container,
        )

    if backend == "ssh_remote":
        host = _simulation_ssh_host(workspace)
        return LinuxBridgeHardwareControl(
            SshCommandChannel(host),
            LinuxSystemdCommandBuilder(),
            host=host,
        )

    if backend == "mujoco":
        return MujocoBridgeHardwareControl()

    raise GarDomainError(f"hardware controlはこのsimulation environmentに未対応です: {backend or '(未設定)'}")


def docker_spec_for(
    settings: DockerSettings,
    *,
    target_id: str | None,
) -> DockerHostSpec:
    """container の形は target 定義が決め、workspace 設定は上書きだけを担当する。"""

    manifest = target_by_id(discover_target_manifests(), target_id)
    spec = (
        docker_host_spec(manifest.simulation_settings(BACKEND_ID), root=gar_tools_root())
        if manifest is not None
        else None
    )

    image = settings.image
    published_port = settings.bridge_port
    if spec is None:
        if not image:
            raise GarDomainError(
                "simulation container の image を決められません。"
                "gar config で target を選ぶか、workspace の docker.image を設定してください"
            )
        spec = DockerHostSpec(image=image)

    return DockerHostSpec(
        image=image or spec.image,
        run_options=spec.run_options,
        init_command=spec.init_command,
        published_bridge_port=(published_port if published_port is not None else spec.published_bridge_port),
        container_bridge_port=spec.container_bridge_port,
        published_host=spec.published_host,
        build_context=spec.build_context,
        build_context_fingerprint=spec.build_context_fingerprint,
    )


def _container_name(workspace: Workspace) -> str:
    return workspace.docker.container or DEFAULT_CONTAINER


def _simulation_ssh_host(workspace: Workspace) -> str:
    host = workspace.simulation_ssh_host
    if not host:
        raise GarDomainError(f"simulation hostのSSH aliasが未設定です: {workspace.name}")
    return host


def _simulation_host_provider(workspace: Workspace) -> str:
    provider = workspace.simulation_host_provider
    if provider:
        return provider
    raise GarDomainError(f"simulation host providerが未設定です: {workspace.name}")


def _ssm_settings(workspace: Workspace) -> tuple[str, str]:
    instance_id = workspace.ec2.instance_id
    region = workspace.ec2.region
    missing = [
        name
        for name, value in (("instance_id", instance_id), ("region", region))
        if not isinstance(value, str) or not value
    ]
    if missing:
        raise GarDomainError(f"AWS SSM設定が不足しています ({', '.join(missing)}): {workspace.name}")
    return instance_id, region


def _wokwi_project_dir(workspace: Workspace) -> Path:
    configured = os.environ.get("GAR_WOKWI_PROJECT_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if workspace.connection_type == "local":
        return workspace.local_root / ".gar" / "wokwi" / "m5stackc"
    return PROJECT_ROOT / ".gar" / "wokwi" / workspace.id
