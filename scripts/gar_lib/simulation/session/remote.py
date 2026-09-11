"""User-facing SSH session helpers for remote simulation environments."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

from scripts.gar_lib.access.display import run_displayed
from scripts.gar_lib.core.config import PROJECT_ROOT, is_valid_runtime_host
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.vscode.profile_manage import write_vscode_terminal_profile


def start_sim_port_forward(host: str, *, panel_port: int = 8080) -> int:
    return _port_forward(host, panel_port=panel_port)


def stop_sim_port_forward(host: str, *, panel_port: int = 8080) -> int:
    return _port_forward(host, "--stop", panel_port=panel_port)


def status_sim_port_forward(host: str, *, panel_port: int = 8080) -> int:
    return _port_forward(host, "--status", panel_port=panel_port)


def _port_forward(host: str, action: str | None = None, *, panel_port: int = 8080) -> int:
    command = [sys.executable, str(PROJECT_ROOT / "tools" / "forward_sim_ports.py"), "--host", host]
    command.extend(("--http", str(panel_port)))
    if action:
        command.append(action)
    return run_displayed(command, runner=subprocess.run, check=False).returncode


def write_sim_terminal_profile(
    *,
    host: str,
    settings: str | None = None,
    profile_name: str | None = None,
) -> None:
    home = Path.home()
    default_settings = (
        Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "Code" / "User" / "settings.json"
        if os.name == "nt"
        else home / ".vscode-server" / "data" / "Machine" / "settings.json"
    )
    settings_path = Path(settings or os.environ.get("GAR_SIM_SETTINGS", str(default_settings))).expanduser()
    selected_profile_name = profile_name or os.environ.get(
        "GAR_SIM_PROFILE_NAME",
        "GAR Simulation Host",
    )
    terminal_bin = home / ".local" / "bin" / ("gar-sim-terminal.cmd" if os.name == "nt" else "gar-sim-terminal")
    terminal_bin.parent.mkdir(parents=True, exist_ok=True)
    terminal_bin.write_text(sim_terminal_script(host), encoding="utf-8")
    terminal_bin.chmod(0o755)
    write_vscode_terminal_profile(settings_path, selected_profile_name, terminal_bin)
    print(f"Terminal:  {terminal_bin}")
    print(f"Profile:   {selected_profile_name}")


def sim_terminal_script(host: str) -> str:
    if not is_valid_runtime_host(host):
        raise GarDomainError(f"Simulation HostのSSH aliasが不正です: {host!r}")
    if os.name == "nt":
        return f'@echo off\r\nssh -F "%USERPROFILE%\\.ssh\\config" -t {host} "cd ~ && exec bash -l"\r\n'
    quoted_host = shlex.quote(host)
    return f"""#!/usr/bin/env bash
set -euo pipefail

exec ssh -F "$HOME/.ssh/config" -t {quoted_host} "cd ~ && exec bash -l"
"""
