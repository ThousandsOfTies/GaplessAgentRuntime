"""`agp sim` subcommand: simulation runtime control over SSH."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

from scripts.agp_lib._config import (
    PROJECT_ROOT,
    default_ec2_host,
    load_config,
)
from scripts.agp_lib._vscode import write_vscode_terminal_profile


def run_sim_command(
    command: str,
    *,
    host: str | None = None,
    settings: str | None = None,
    profile_name: str | None = None,
    port_forward: bool = True,
    stop_port_forward: bool = True,
) -> int:
    commands = {
        "start": (
            'setsid bash -c "nohup ~/venv/bin/python3 ~/web-bridge/bridge.py '
            '> /tmp/bridge.log 2>&1 &" < /dev/null; '
            "sleep 2; "
            'setsid bash -c "sudo nohup ~/cuse_i2c -f --devname=i2c-1 '
            '> /tmp/cuse.log 2>&1 &" < /dev/null; '
            "sleep 3; "
            "sudo chmod 666 /dev/i2c-1; "
            'pgrep -af "bridge.py|cuse_i2c"'
        ),
        "stop": (
            "pkill -f cuse_i2c || true; "
            "pkill -f bridge.py || true; "
            'echo "Simulation device runtime stopped."'
        ),
        "diag": (
            'echo "--- processes ---"; '
            'pgrep -af "bridge.py|cuse_i2c" || true; '
            'echo "--- devices ---"; '
            "ls -l /dev/i2c-1 /dev/gpiochip0 /dev/spidev0.0 2>/dev/null || true; "
            'echo "--- api ---"; '
            "curl -s http://127.0.0.1:8080/api/state || true"
        ),
        "log": (
            'echo "--- bridge.log ---"; '
            "tail -n 80 /tmp/bridge.log 2>/dev/null; "
            'echo "--- cuse.log ---"; '
            "tail -n 80 /tmp/cuse.log 2>/dev/null"
        ),
    }

    if command == "status":
        resolved_host = host or default_ec2_host(load_config())
        port_forward_result = status_sim_port_forward(resolved_host)
        state_result = show_sim_state(resolved_host)
        return port_forward_result or state_result

    remote_command = commands.get(command)
    if remote_command is None:
        print(f"unknown sim command: {command}", file=sys.stderr)
        return 1

    resolved_host = host or default_ec2_host(load_config())

    result = subprocess.run(
        ["ssh", "-F", str(Path.home() / ".ssh" / "config"), resolved_host, remote_command],
        check=False,
    )
    if result.returncode != 0:
        return result.returncode

    if command == "start":
        write_sim_terminal_profile(
            host=resolved_host,
            settings=settings,
            profile_name=profile_name,
        )
        if port_forward:
            return start_sim_port_forward(resolved_host)

    if command == "stop" and stop_port_forward:
        return stop_sim_port_forward(resolved_host)

    return 0


def start_sim_port_forward(host: str) -> int:
    return subprocess.run(
        [str(PROJECT_ROOT / "tools" / "forward_ec2_ports.sh"), "--host", host],
        check=False,
    ).returncode


def stop_sim_port_forward(host: str) -> int:
    return subprocess.run(
        [str(PROJECT_ROOT / "tools" / "forward_ec2_ports.sh"), "--host", host, "--stop"],
        check=False,
    ).returncode


def status_sim_port_forward(host: str) -> int:
    return subprocess.run(
        [str(PROJECT_ROOT / "tools" / "forward_ec2_ports.sh"), "--host", host, "--status"],
        check=False,
    ).returncode


def show_sim_state(host: str) -> int:
    print("--- bridge state ---")
    return subprocess.run(
        [
            "ssh",
            "-F",
            str(Path.home() / ".ssh" / "config"),
            host,
            "curl -s http://127.0.0.1:8080/api/state",
        ],
        check=False,
    ).returncode


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
            "AGP_SIM_SETTINGS",
            str(home / ".vscode-server" / "data" / "Machine" / "settings.json"),
        )
    ).expanduser()
    selected_profile_name = profile_name or os.environ.get(
        "AGP_SIM_PROFILE_NAME",
        "EC2 Simulation",
    )
    terminal_bin = home / ".local" / "bin" / "agp-sim-terminal"
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
