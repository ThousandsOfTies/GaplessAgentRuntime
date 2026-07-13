"""Resolve physical target runtimes and compose them with access channels."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from scripts.gar_lib.access.adb import AdbFileChannel, AdbShellChannel
from scripts.gar_lib.access.ssh import ScpFileChannel, SshCommandChannel
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.target.environment import TargetEnvironment
from scripts.gar_lib.target.esp32 import Esp32ArtifactInstaller
from scripts.gar_lib.target.file_transfer import FileTransferTargetEnvironment
from scripts.gar_lib.target.serial import SerialTargetEnvironment


def _string(mapping: Mapping[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    return value if isinstance(value, str) and value else None


def _windows_path(path: Path) -> str:
    completed = subprocess.run(
        ("wslpath", "-w", str(path)),
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 and completed.stdout.strip() else str(path)


class ConfigTargetEnvironmentResolver:
    def for_workspace(self, workspace: Workspace) -> TargetEnvironment:
        environment_id = workspace.selected_environments.get("target")
        serial = _string(workspace.target, "serial")
        base_destination = _string(workspace.target, "dest") or "/home/user"

        if environment_id == "adb_usb":
            return FileTransferTargetEnvironment(
                AdbShellChannel(serial),
                AdbFileChannel(serial),
                base_destination=base_destination,
            )

        if environment_id == "adb_win":
            executable = _string(workspace.adb, "exe_path") or shutil.which("adb.exe")
            if executable is None:
                raise GarDomainError("adb.exeが見つかりません。gar setupで実機環境を設定してください。")
            return FileTransferTargetEnvironment(
                AdbShellChannel(serial, executable=executable),
                AdbFileChannel(
                    serial,
                    executable=executable,
                    local_path_transform=_windows_path,
                ),
                base_destination=base_destination,
            )

        if environment_id == "ssh_scp":
            host = _string(workspace.target, "host")
            if host is None and workspace.connection_type == "network":
                host = _string(workspace.connection, "host")
            if host is None:
                raise GarDomainError(
                    f"実機のSSH hostが未設定です: {workspace.name}。gar setupで設定してください。"
                )
            return FileTransferTargetEnvironment(
                SshCommandChannel(host),
                ScpFileChannel(host),
                base_destination=base_destination,
            )

        if environment_id == "esp32_esptool":
            port = _string(workspace.target, "port") or _string(workspace.esp32, "port")
            if port is None:
                raise GarDomainError(
                    f"ESP32 serial portが未設定です: {workspace.name}。gar setupで設定してください。"
                )
            return SerialTargetEnvironment(Esp32ArtifactInstaller(port))

        raise GarDomainError(f"target environmentはまだ未対応です: {environment_id or '(未設定)'}")
