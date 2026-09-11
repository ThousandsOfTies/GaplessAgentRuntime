"""Compose a target runtime from the environment selected by a workspace."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from scripts.gar_lib.access.adb import AdbFileChannel, AdbShellChannel
from scripts.gar_lib.access.ssh import ScpFileChannel, SshCommandChannel
from scripts.gar_lib.artifacts.provenance import collect_target_tools_provenance
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.tools_repository import gar_tools_root
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.target.environment import TargetEnvironment
from scripts.gar_lib.target.esp32 import Esp32TargetEnvironment
from scripts.gar_lib.target.file_transfer import FileTransferTargetEnvironment
from scripts.gar_lib.target.lifecycle import CommandTargetLifecycle, TargetLifecycle
from scripts.gar_lib.target.manifest import TargetManifest, discover_target_manifests, target_by_id
from scripts.gar_lib.target.uuu import UuuTargetEnvironment


def target_environment_for(workspace: Workspace) -> TargetEnvironment:
    """実機へ成果物を配置するオブジェクトを作る。"""

    backend = workspace.selected_environments.target
    serial = workspace.target.serial
    base_destination = workspace.target.dest or "/home/user"

    if backend == "adb_usb":
        return FileTransferTargetEnvironment(
            AdbShellChannel(serial),
            AdbFileChannel(serial),
            base_destination=base_destination,
        )

    if backend == "adb_win":
        executable = workspace.adb.exe_path or shutil.which("adb.exe")
        if executable is None:
            raise GarDomainError("adb.exeが見つかりません。gar configで実機環境を設定してください。")
        return FileTransferTargetEnvironment(
            AdbShellChannel(serial, executable=executable),
            AdbFileChannel(serial, executable=executable, local_path_transform=_windows_path),
            base_destination=base_destination,
        )

    if backend == "ssh_scp":
        host = _ssh_host(workspace)
        recipe = None
        lifecycle = None
        active_tools_provenance = None
        manifest = _selected_target_manifest(workspace)
        if manifest is not None:
            recipe = manifest.provisioning_recipe_path(backend)
            lifecycle = manifest.lifecycle_capability(backend)
            if manifest.source_path is None:
                raise GarDomainError(f"Target定義のgar-tools provenanceを解決できません: {manifest.id}")
            active_tools_provenance = collect_target_tools_provenance(
                manifest.source_path,
                backend,
                target_id=manifest.id,
            )
        return FileTransferTargetEnvironment(
            SshCommandChannel(host),
            ScpFileChannel(host),
            base_destination=base_destination,
            privileged_install=recipe is not None,
            prepare_recipe=recipe,
            prepare_lifecycle=lifecycle is not None,
            app_install_action="register-app" if lifecycle is not None else "enable-app",
            active_tools_provenance=active_tools_provenance,
            require_active_tools_provenance=True,
        )

    if backend == "esp32_esptool":
        port = workspace.target.port or workspace.esp32.port
        if port is None:
            raise GarDomainError(f"ESP32 serial portが未設定です: {workspace.name}。gar configで設定してください。")
        return Esp32TargetEnvironment(port)

    if backend == "uuu":
        manifest = _selected_target_manifest(workspace)
        if manifest is None:
            raise GarDomainError("UUU targetには選択されたTarget manifestが必要です")
        return UuuTargetEnvironment(manifest, console_port=workspace.target.serial)

    raise GarDomainError(f"target environmentはまだ未対応です: {backend or '(未設定)'}")


def target_lifecycle_for(workspace: Workspace) -> TargetLifecycle | None:
    """Compose the lifecycle capability declared by the selected Target recipe."""

    backend = workspace.selected_environments.target
    if backend != "ssh_scp":
        return None
    manifest = _selected_target_manifest(workspace)
    if manifest is None:
        return None
    capability = manifest.lifecycle_capability(backend)
    if capability is None:
        return None
    return CommandTargetLifecycle(
        SshCommandChannel(_ssh_host(workspace)), capability.command, supports_stop=capability.stop
    )


def _selected_target_manifest(workspace: Workspace) -> TargetManifest | None:
    if workspace.selected_target is None:
        return None
    manifest = target_by_id(
        discover_target_manifests(tools_root=_workspace_tools_root(workspace)),
        workspace.selected_target,
    )
    if manifest is None:
        raise GarDomainError(f"選択したTarget定義が見つかりません: {workspace.selected_target}")
    return manifest


def _workspace_tools_root(workspace: Workspace) -> Path:
    """Prefer the Product-pinned tools checkout for local Target operations."""

    if workspace.connection_type == "local":
        candidate = workspace.local_root / "sources" / "gar-tools"
        if (candidate / "targets").is_dir():
            return candidate
    return gar_tools_root()


def _ssh_host(workspace: Workspace) -> str:
    host = workspace.target.host
    if host is None and workspace.connection_type == "network":
        host = workspace.connection.host
    if host is None:
        raise GarDomainError(f"実機のSSH hostが未設定です: {workspace.name}。gar configで設定してください。")
    return host


def _windows_path(path: Path) -> str:
    if os.name == "nt":
        return str(path)
    completed = subprocess.run(
        ("wslpath", "-w", str(path)),
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 and completed.stdout.strip() else str(path)
