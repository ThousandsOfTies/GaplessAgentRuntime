"""User-facing SSH session helpers for remote simulation environments."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from scripts.gar_lib.config import PROJECT_ROOT
from scripts.gar_lib.vscode.profile_manage import write_vscode_terminal_profile


def start_sim_port_forward(host: str) -> int:
    return _port_forward(host)


def stop_sim_port_forward(host: str) -> int:
    return _port_forward(host, "--stop")


def status_sim_port_forward(host: str) -> int:
    return _port_forward(host, "--status")


def _port_forward(host: str, action: str | None = None) -> int:
    command = [str(PROJECT_ROOT / "tools" / "forward_ec2_ports.sh"), "--host", host]
    if action:
        command.append(action)
    return subprocess.run(command, check=False).returncode


def write_sim_terminal_profile(
    *,
    host: str,
    settings: str | None = None,
    profile_name: str | None = None,
) -> None:
    home = Path.home()
    settings_path = Path(
        settings
        or os.environ.get(
            "GAR_SIM_SETTINGS",
            str(home / ".vscode-server" / "data" / "Machine" / "settings.json"),
        )
    ).expanduser()
    selected_profile_name = profile_name or os.environ.get(
        "GAR_SIM_PROFILE_NAME",
        "EC2 Simulation",
    )
    terminal_bin = home / ".local" / "bin" / "gar-sim-terminal"
    terminal_bin.parent.mkdir(parents=True, exist_ok=True)
    terminal_bin.write_text(sim_terminal_script(host), encoding="utf-8")
    terminal_bin.chmod(0o755)
    write_vscode_terminal_profile(settings_path, selected_profile_name, terminal_bin)
    print(f"Terminal:  {terminal_bin}")
    print(f"Profile:   {selected_profile_name}")


def sim_terminal_script(host: str) -> str:
    quoted_host = shlex.quote(host)
    return f"""#!/usr/bin/env bash
set -euo pipefail

exec ssh -F "$HOME/.ssh/config" -t {quoted_host} "cd ~ && exec bash -l"
"""
