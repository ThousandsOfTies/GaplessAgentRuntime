from __future__ import annotations

import shutil
import subprocess
from abc import ABC
from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class CommandStatus:
    name: str
    path: str | None

    @property
    def installed(self) -> bool:
        return self.path is not None


class EnvironmentSetupOption(ABC):
    """Setup option metadata and dependency installation contract.

    Runtime behavior belongs to the dedicated build, simulation, target, and
    access layers. Registry entries intentionally do not execute GAR commands.
    """

    provider_id: ClassVar[str]
    display_name: ClassVar[str]
    description: ClassVar[str]
    category_id: ClassVar[str] = "uncategorized"
    category_name: ClassVar[str] = "Uncategorized"
    category_order: ClassVar[int] = 100
    display_order: ClassVar[int] = 100
    required_commands: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def dependency_status(cls) -> list[CommandStatus]:
        return [
            CommandStatus(name=command, path=shutil.which(command))
            for command in cls.required_commands
        ]

    @classmethod
    def missing_commands(cls) -> list[str]:
        return [
            status.name
            for status in cls.dependency_status()
            if not status.installed
        ]

    @classmethod
    def install_hint(cls, missing: list[str]) -> str:
        commands = ", ".join(missing)
        return f"Install the missing command(s): {commands}"

    @classmethod
    def install_dependencies(cls, missing: list[str]) -> int:
        print(cls.install_hint(missing))
        return 1

    @classmethod
    def run_install_command(cls, argv: list[str]) -> int:
        return subprocess.run(argv, check=False).returncode
