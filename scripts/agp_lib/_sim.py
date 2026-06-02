"""`agp sim` subcommand: simulation runtime control over SSH."""

from __future__ import annotations

import json
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

# Machine-readable diag: emit section markers so the WSL side can parse the
# remote output into structured JSON. Devices are probed as "<path> 0|1".
SIM_DIAG_DEVICES = ("/dev/i2c-1", "/dev/gpiochip0", "/dev/spidev0.0")
SIM_DIAG_JSON_COMMAND = (
    'echo "@@PROC@@"; '
    'pgrep -af "bridge.py|cuse_i2c" || true; '
    'echo "@@DEV@@"; '
    "for d in " + " ".join(SIM_DIAG_DEVICES) + "; do "
    'if [ -e "$d" ]; then echo "$d 1"; else echo "$d 0"; fi; done; '
    'echo "@@API@@"; '
    "curl -s http://127.0.0.1:8080/api/state || true"
)


def parse_sim_diag(raw: str) -> dict:
    """Parse the marker-delimited ``SIM_DIAG_JSON_COMMAND`` output into a dict.

    Returns ``{"processes": [...], "devices": {...}, "api": ... | None, "ok": bool}``.
    ``ok`` is True when at least one runtime process is alive and the bridge API
    returned parseable JSON.
    """
    section = None
    proc_lines: list[str] = []
    device_lines: list[str] = []
    api_lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped == "@@PROC@@":
            section = "proc"
            continue
        if stripped == "@@DEV@@":
            section = "dev"
            continue
        if stripped == "@@API@@":
            section = "api"
            continue
        if section == "proc":
            if stripped:
                proc_lines.append(stripped)
        elif section == "dev":
            if stripped:
                device_lines.append(stripped)
        elif section == "api":
            api_lines.append(line)

    processes = []
    for line in proc_lines:
        pid, _, cmd = line.partition(" ")
        if pid.isdigit():
            processes.append({"pid": int(pid), "cmd": cmd.strip()})

    devices: dict[str, bool] = {}
    for line in device_lines:
        path, _, flag = line.rpartition(" ")
        if path:
            devices[path] = flag == "1"

    api_text = "\n".join(api_lines).strip()
    api: object | None
    try:
        api = json.loads(api_text) if api_text else None
    except json.JSONDecodeError:
        api = None

    ok = bool(processes) and api is not None
    return {"processes": processes, "devices": devices, "api": api, "ok": ok}


def run_sim_diag_json(host: str) -> int:
    """Run ``agp sim diag --json``: print structured JSON, exit 0 when ok."""
    result = subprocess.run(
        ["ssh", "-F", str(Path.home() / ".ssh" / "config"), host, SIM_DIAG_JSON_COMMAND],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        payload = {
            "processes": [],
            "devices": {},
            "api": None,
            "ok": False,
            "error": f"ssh exited {result.returncode}",
            "stderr": result.stderr.strip(),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return result.returncode

    payload = parse_sim_diag(result.stdout)
    payload["host"] = host
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


def run_sim_command(
    command: str,
    *,
    host: str | None = None,
    settings: str | None = None,
    profile_name: str | None = None,
    port_forward: bool = True,
    stop_port_forward: bool = True,
    json_output: bool = False,
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

    if command == "diag" and json_output:
        resolved_host = host or default_ec2_host(load_config())
        return run_sim_diag_json(resolved_host)

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
