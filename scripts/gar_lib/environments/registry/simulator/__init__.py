"""Explicit registry of simulation environments."""

from scripts.gar_lib.environments.registry.simulator.product_hook import ProductHookEnvironment
from scripts.gar_lib.environments.registry.simulator.aws_ssm import AwsSsmEnvironment
from scripts.gar_lib.environments.registry.simulator.esp32_qemu import (
    Esp32QemuFirmwareEnvironment,
)
from scripts.gar_lib.environments.registry.simulator.mujoco import MujocoEnvironment
from scripts.gar_lib.environments.registry.simulator.renode_mcu import RenodeMcuEnvironment
from scripts.gar_lib.environments.registry.simulator.ssh_remote import SshRemoteEnvironment
from scripts.gar_lib.environments.registry.simulator.wokwi import WokwiEnvironment
from scripts.gar_lib.environments.setup_option import EnvironmentSetupOption

ENVIRONMENT_OPTIONS: tuple[type[EnvironmentSetupOption], ...] = (
    ProductHookEnvironment,
    Esp32QemuFirmwareEnvironment,
    WokwiEnvironment,
    MujocoEnvironment,
    AwsSsmEnvironment,
    SshRemoteEnvironment,
    RenodeMcuEnvironment,
)
