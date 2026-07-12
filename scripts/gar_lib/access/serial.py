"""Serial firmware installation and console capabilities."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence

from scripts.gar_lib.access.base import CommandResult, ConsoleSession
from scripts.gar_lib.core.artifact import Artifact


class SerialArtifactInstaller:
    """Install an artifact with a target-specific serial command builder."""

    def __init__(self, command_builder: Callable[[Artifact], Sequence[str]]):
        self.command_builder = command_builder

    def install(self, artifact: Artifact) -> CommandResult:
        argv = tuple(self.command_builder(artifact))
        completed = subprocess.run(argv, check=False, capture_output=True, text=True)
        return CommandResult(argv, completed.returncode, completed.stdout, completed.stderr)


class SerialConsoleChannel:
    def __init__(
        self,
        port: str,
        *,
        baud: int = 115200,
        executable: str = "picocom",
    ):
        self.port = port
        self.baud = baud
        self.executable = executable

    def open(self) -> ConsoleSession:
        process = subprocess.Popen((self.executable, "--baud", str(self.baud), self.port))
        return ConsoleSession(process)
