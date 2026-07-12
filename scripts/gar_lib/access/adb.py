"""ADB shell and file channels."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.gar_lib.access.base import CommandResult, TransferResult
from scripts.gar_lib.core.errors import AccessConnectionError


def _connection_reason(stderr: str) -> str | None:
    lowered = stderr.lower()
    for marker, reason in (
        ("no devices/emulators found", "no_device"),
        ("device offline", "device_offline"),
        ("device unauthorized", "device_unauthorized"),
        ("device not found", "device_not_found"),
    ):
        if marker in lowered:
            return reason
    return None


class _AdbChannel:
    def __init__(self, serial: str | None = None, *, executable: str = "adb"):
        self.serial = serial
        self.executable = executable

    def _prefix(self) -> tuple[str, ...]:
        return (self.executable, "-s", self.serial) if self.serial else (self.executable,)

    def _raise_connection_error(self, returncode: int, stderr: str) -> None:
        reason = _connection_reason(stderr)
        if reason:
            raise AccessConnectionError(
                channel="adb",
                endpoint=self.serial or "default",
                reason=reason,
                returncode=returncode,
            )


class AdbShellChannel(_AdbChannel):
    def run(self, command: str) -> CommandResult:
        argv = (*self._prefix(), "shell", command)
        completed = subprocess.run(argv, check=False, capture_output=True, text=True)
        self._raise_connection_error(completed.returncode, completed.stderr)
        return CommandResult(argv, completed.returncode, completed.stdout, completed.stderr)


class AdbFileChannel(_AdbChannel):
    def push(self, source: Path, destination: str) -> TransferResult:
        return self._run("push", str(source), destination)

    def pull(self, source: str, destination: Path) -> TransferResult:
        return self._run("pull", source, str(destination))

    def _run(self, action: str, source: str, destination: str) -> TransferResult:
        argv = (*self._prefix(), action, source, destination)
        completed = subprocess.run(argv, check=False, capture_output=True, text=True)
        self._raise_connection_error(completed.returncode, completed.stderr)
        return TransferResult(argv, completed.returncode, completed.stdout, completed.stderr)
