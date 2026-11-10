from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    path: str | None

    @property
    def installed(self) -> bool:
        return self.path is not None


class EnvironmentSetupOption:
    """Setup option metadata and dependency installation contract.

    Runtime behavior belongs to the dedicated build, simulation, target, and
    access layers. Registry entries intentionally do not execute GAR commands.
    """

    environment_id: ClassVar[str]
    display_name: ClassVar[str]
    description: ClassVar[str]
    category_id: ClassVar[str] = "uncategorized"
    category_name: ClassVar[str] = "Uncategorized"
    category_order: ClassVar[int] = 100
    display_order: ClassVar[int] = 100
    required_commands: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def setup_priority(cls) -> int:
        """Return the host-specific menu order; lower values are offered first."""
        return cls.display_order

    @classmethod
    def dependency_status(cls) -> list[DependencyStatus]:
        return [DependencyStatus(name=command, path=shutil.which(command)) for command in cls.required_commands]

    @classmethod
    def missing_commands(cls) -> list[str]:
        return [status.name for status in cls.dependency_status() if not status.installed]

    @classmethod
    def install_hint(cls, missing: list[str]) -> str:
        commands = ", ".join(missing)
        return f"Install the missing command(s): {commands}"

    @classmethod
    def install_dependencies(cls, missing: list[str]) -> int:
        print(cls.install_hint(missing))
        return 1

    @classmethod
    def record_detected_configuration(cls, config: dict) -> None:
        """Persist environment-specific values discovered during setup."""

    @classmethod
    def run_install_command(cls, argv: list[str]) -> int:
        return subprocess.run(argv, check=False).returncode


class DevelopmentEnvironmentSetupOption(EnvironmentSetupOption):
    """An executor used to build and test product source."""

    category_id = "codespace"
    # ``codespace`` is the persisted v1 key.  The user-facing role is Build;
    # local source is no longer assumed to execute hooks on the host OS.
    category_name = "Build環境"
    category_order = 10


class SimulationEnvironmentSetupOption(EnvironmentSetupOption):
    """An environment used to run a simulated target."""

    category_id = "simulator"
    category_name = "シミュレート環境"
    category_order = 20


class SimulationHostSetupOption(EnvironmentSetupOption):
    """A compute provider that hosts an SSH-accessed Linux simulator."""

    category_id = "simulation_host"
    category_name = "Sim Host"
    category_order = 25


class TargetEnvironmentSetupOption(EnvironmentSetupOption):
    """An environment used to deploy to a physical target."""

    category_id = "target"
    category_name = "実機環境"
    category_order = 30
