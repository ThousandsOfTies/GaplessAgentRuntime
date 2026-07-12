"""Capability-oriented access channels."""

from scripts.gar_lib.access.adb import AdbFileChannel, AdbShellChannel
from scripts.gar_lib.access.base import (
    ArtifactInstaller,
    CommandChannel,
    CommandResult,
    ConsoleChannel,
    ConsoleSession,
    FileChannel,
    TransferResult,
)
from scripts.gar_lib.access.serial import SerialArtifactInstaller, SerialConsoleChannel
from scripts.gar_lib.access.ssh import ScpFileChannel, SshCommandChannel

__all__ = [
    "AdbFileChannel",
    "AdbShellChannel",
    "ArtifactInstaller",
    "CommandChannel",
    "CommandResult",
    "ConsoleChannel",
    "ConsoleSession",
    "FileChannel",
    "ScpFileChannel",
    "SerialArtifactInstaller",
    "SerialConsoleChannel",
    "SshCommandChannel",
    "TransferResult",
]
