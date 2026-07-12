"""Small interfaces describing what an access mechanism can do."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from scripts.gar_lib.core.artifact import Artifact


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class TransferResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class ConsoleSession:
    process: subprocess.Popen[bytes]


class CommandChannel(Protocol):
    def run(self, command: str) -> CommandResult: ...


class FileChannel(Protocol):
    def push(self, source: Path, destination: str) -> TransferResult: ...

    def pull(self, source: str, destination: Path) -> TransferResult: ...


class ArtifactInstaller(Protocol):
    def install(self, artifact: Artifact) -> CommandResult: ...


class ConsoleChannel(Protocol):
    def open(self) -> ConsoleSession: ...
