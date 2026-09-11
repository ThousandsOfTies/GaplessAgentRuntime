"""Configured command capabilities; inspection never contacts an execution host."""

from __future__ import annotations

from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.target.composition import _selected_target_manifest

COMMON_ACTIONS = ("prepare", "build", "deploy", "start", "stop", "status", "log", "diag")
BUILD_BACKENDS = {"local", "native", "docker", "github_codespaces"}
SIM_BACKENDS = {"ssh_remote", "local_docker", "wokwi", "mujoco"}


def simulation_actions(workspace: Workspace) -> dict[str, bool]:
    """The same offline contract governs capability output and API execution."""

    flags = dict.fromkeys(COMMON_ACTIONS, False)
    backend = workspace.selected_environments.simulator
    if backend in SIM_BACKENDS:
        flags.update(dict.fromkeys(("deploy", "start", "stop", "status", "log", "diag"), True))
        flags["build"] = workspace.selected_environments.codespace in BUILD_BACKENDS
        flags["prepare"] = backend in {"ssh_remote", "local_docker"}
    return flags


def require_simulation_action(workspace: Workspace, action: str) -> None:
    """Reject unsupported operations before composing tools, artifacts, or hosts."""

    capability = "build" if action == "clean" else action
    if not simulation_actions(workspace).get(capability, False):
        backend = workspace.selected_environments.simulator or "(未設定)"
        detail = ""
        if backend in SIM_BACKENDS and capability == "build":
            build = workspace.selected_environments.codespace or "(未設定)"
            detail = f"。BuildEnvironmentを確認してください: {build}"
        raise GarDomainError(f"{backend} SimulationEnvironmentの{action}は未対応です{detail}")


def command_capabilities(group: str, workspace: Workspace) -> dict[str, object]:
    flags = dict.fromkeys(COMMON_ACTIONS, False)
    if group == "code":
        backend = workspace.selected_environments.codespace or "local"
        if backend in {"local", "github_codespaces"}:
            flags.update(prepare=True, start=True, stop=True, status=True, diag=True)
        flags["log"] = backend == "github_codespaces"
        reason = "logはCodespace作成log。build/deployはsim/targetで実行します"
    elif group == "sim":
        backend = workspace.selected_environments.simulator
        flags = simulation_actions(workspace)
        reason = "prepareはLinux Sim Hostの初期準備。hostを持たないbackendには不要です"
    elif group == "target":
        backend = workspace.selected_environments.target
        flags["build"] = workspace.selected_environments.codespace in BUILD_BACKENDS
        flags["deploy"] = backend in {"ssh_scp", "adb_usb", "adb_win", "esp32_esptool", "uuu"}
        manifest = _selected_target_manifest(workspace) if backend == "ssh_scp" else None
        lifecycle = manifest.lifecycle_capability(backend) if manifest is not None else None
        flags["prepare"] = manifest is not None and bool(manifest.provisioning_settings(backend).get("path"))
        if lifecycle is not None:
            flags.update(start=True, status=True, log=True, diag=True, stop=lifecycle.stop)
        reason = "start/stop/status/log/diagは選択したTarget recipeの宣言に従います"
    else:
        raise ValueError(f"unknown command group: {group}")
    return {"environment": backend, "actions": flags, "reason": reason}
