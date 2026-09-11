"""Read-only development environment observations and bounded creation logs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from scripts.gar_lib.commands.code_connection import run_gh_captured
from scripts.gar_lib.commands.code_state import CodespaceConnectionState, codespace_state_path
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.observation import EnvironmentObservation, component, unavailable
from scripts.gar_lib.core.workspace import Workspace


def _selected_name(workspace: Workspace, explicit: str | None, state: CodespaceConnectionState | None) -> str | None:
    return (
        explicit
        or workspace.connection.codespace
        or os.environ.get("GAR_CODESPACE_NAME")
        or (state.codespace_name if state else None)
    )


def observe_code(
    workspace: Workspace, *, action: str, codespace: str | None = None, mount_dir: str | None = None
) -> EnvironmentObservation:
    backend = workspace.selected_environments.codespace or "local"
    parts = {
        "runtime": unavailable("development環境ではsim/target runtimeを実行しません"),
        "app": unavailable("applicationはsim/targetで観測します"),
    }
    if backend == "local":
        root = workspace.local_root
        ready = root.is_dir()
        parts.update(
            host=component("available", True),
            connection=component("available" if ready else "missing", ready, path=str(root)),
        )
    elif backend == "github_codespaces":
        # The ordinary state loader migrates legacy files. Diagnostics only read.
        state = CodespaceConnectionState.load(codespace_state_path())
        selected = _selected_name(workspace, codespace, state)
        try:
            result = run_gh_captured(
                ["gh", "codespace", "list", "--json", "name,state"],
                timeout=30,
                label="inspect Codespaces",
                command_name=f"gar code {action}",
            )
            if result is None or result.returncode:
                raise GarDomainError("Codespaceの状態を取得できません。認証とghを確認してください")
            rows = json.loads(result.stdout)
            if not isinstance(rows, list) or any(
                not isinstance(row, dict) or not isinstance(row.get("name"), str) for row in rows
            ):
                raise GarDomainError("Codespace一覧の形式が不正です")
            if selected is None and len(rows) == 1:
                selected = rows[0]["name"]
            row = next((row for row in rows if row.get("name") == selected), None)
            if row is None:
                raise GarDomainError("Codespaceを一意に特定できません。--codespace NAMEを指定してください")
            if not selected or selected.startswith("-") or any(char in selected for char in "\r\n\0"):
                raise GarDomainError("Codespace名が不正です")
            running = row.get("state") == "Available"
            parts["host"] = component(
                "running" if running else str(row.get("state", "unknown")).lower(), running, codespace=selected
            )
            configured = state is not None and state.codespace_name == selected
            parts["connection"] = component(
                "configured" if configured else "not_configured", configured, verification="local_state"
            )
            if mount_dir is not None:
                selected_mount = Path(mount_dir).expanduser()
                mount = {"path": str(selected_mount), "state": "not_used" if os.name == "nt" else "unknown"}
                if os.name != "nt" and shutil.which("findmnt"):
                    mounted = subprocess.run(
                        ["findmnt", "-n", "-o", "SOURCE", "--target", str(selected_mount)],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    expected = f"{state.ssh_host}:{state.remote_path}" if configured else None
                    mount["state"] = (
                        "mounted"
                        if expected and mounted.returncode == 0 and mounted.stdout.strip() == expected
                        else "not_mounted"
                    )
                parts["connection"]["mount"] = mount
            if action == "diag" and configured and running:
                # Checking a stopped Codespace by SSH can wake it; only probe an already available one.
                probe = run_gh_captured(
                    ["gh", "codespace", "ssh", "-c", selected, "--", "true"],
                    timeout=30,
                    label="check Codespace connection",
                    command_name="gar code diag",
                )
                reachable = probe is not None and probe.returncode == 0
                parts["connection"].update(
                    state="reachable" if reachable else "unreachable", ok=reachable, verification="ssh_probe"
                )
        except (GarDomainError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            parts.setdefault("host", component("unknown", False, error=str(error)))
            parts["connection"] = component("unknown", False, error=str(error))
    else:
        parts.update(
            host=component("unsupported", False, error=f"code環境に未対応です: {backend}"),
            connection=component("unknown", False),
        )
    return EnvironmentObservation(
        f"code.{action}",
        workspace.name,
        backend,
        {name: parts[name] for name in ("host", "connection", "runtime", "app")},
    )


def prepare_code(workspace: Workspace, *, codespace: str | None = None) -> EnvironmentObservation:
    """Verify development prerequisites, including auth, without waking a VM or installing tools."""
    backend = workspace.selected_environments.codespace or "local"
    commands = ("git",) if backend == "local" else ("git", "gh", "ssh")
    available = {name: shutil.which(name) is not None for name in commands}
    parts = {
        "tools": component(
            "ready" if all(available.values()) else "missing", all(available.values()), commands=available
        )
    }
    if backend == "local":
        ready = workspace.local_root.is_dir()
        parts["workspace"] = component("ready" if ready else "missing", ready)
    elif backend == "github_codespaces" and all(available.values()):
        result = run_gh_captured(
            ["gh", "auth", "status"], timeout=30, label="check GitHub authentication", command_name="gar code prepare"
        )
        authenticated = result is not None and result.returncode == 0
        parts["authentication"] = component("ready" if authenticated else "not_authenticated", authenticated)
        # Configuration is required here; running state is deliberately not a prerequisite.
        state = CodespaceConnectionState.load(codespace_state_path())
        selected = _selected_name(workspace, codespace, state)
        parts["workspace"] = component("configured" if selected else "not_configured", bool(selected))
    elif backend != "github_codespaces":
        parts["workspace"] = component("unsupported", False, error=f"code環境に未対応です: {backend}")
    return EnvironmentObservation("code.prepare", workspace.name, backend, parts)


def code_logs(workspace: Workspace, *, codespace: str | None = None) -> int:
    if workspace.selected_environments.codespace != "github_codespaces":
        raise GarDomainError("code logはCodespacesの作成logに対応します。Local環境には対象logがありません")
    state = CodespaceConnectionState.load(codespace_state_path())
    selected = _selected_name(workspace, codespace, state)
    if not selected or selected.startswith("-") or any(char in selected for char in "\r\n\0"):
        raise GarDomainError("code logには有効な--codespace NAMEまたはworkspaceのCodespace設定が必要です")
    result = run_gh_captured(
        ["gh", "codespace", "logs", "-c", selected],
        timeout=30,
        label="read Codespace creation logs",
        command_name="gar code log",
    )
    if result is None or result.returncode:
        raise GarDomainError("Codespace作成logを取得できませんでした")
    print(result.stdout, end="")
    return 0
