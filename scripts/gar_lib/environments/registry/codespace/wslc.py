"""WSL Containers as an explicitly selected local build environment."""

import os

from scripts.gar_lib.access.wslc import find_wslc
from scripts.gar_lib.environments.setup_option import DependencyStatus, DevelopmentEnvironmentSetupOption


class WslcDevelopmentSetup(DevelopmentEnvironmentSetupOption):
    environment_id = "wslc"
    display_name = "Local WSL Containers"
    description = "WindowsのWSLCでLinux container内のProduct build hookを実行します"
    display_order = 6
    required_commands = ("wslc",)

    @classmethod
    def setup_priority(cls) -> int:
        return 1 if os.name == "nt" else cls.display_order

    @classmethod
    def dependency_status(cls) -> list[DependencyStatus]:
        return [DependencyStatus(name="wslc", path=find_wslc())]

    @classmethod
    def install_hint(cls, missing: list[str]) -> str:
        return "Windows で wsl --update を実行してください。WSL ContainersにはWSL 2.9.3以上が必要です。"
