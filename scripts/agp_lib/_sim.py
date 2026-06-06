"""`agp sim` subcommand: simulation runtime control over SSH."""

from __future__ import annotations

import json
import csv
import io
import os
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path
from urllib.parse import quote

from scripts.agp_lib._sim_cmd import build_gpio_systemd_install_command, build_sim_diag_json_command, build_gpio_sim_setup_command, build_gpio_sim_teardown_command, build_systemd_install_command, build_systemd_start_command, build_systemd_stop_command, build_sim_start_command, build_sim_stop_command, build_sim_status_command, build_sim_log_command, build_gpio_runtime_status_command, build_panel_command
from scripts.agp_lib._sim_parse import parse_sim_diag, parse_gpio_runtime_status, parse_gpio_sim_check
from scripts.agp_lib._config import (
    PROJECT_ROOT,
    default_ec2_host,
    load_config,
)
from scripts.agp_lib._hw import load_hw_definition

from scripts.agp_lib.environments.discovery import discover_environment_providers
from scripts.agp_lib.environments.base import DevEnvironment

def _get_sim_provider() -> type[DevEnvironment]:
    config = load_config()
    pid = config.get("selected_providers", {}).get("simulation")
    providers = discover_environment_providers()
    if pid:
        for p in providers:
            if p.provider_id == pid:
                return p
    for p in providers:
        if p.provider_id == "ssh_remote":
            return p
    raise RuntimeError("No simulation provider found")

from scripts.agp_lib._vscode import write_vscode_terminal_profile

# Machine-readable diag: emit section markers so the WSL side can parse the
# remote output into structured JSON. Devices are probed as "<path> 0|1".
SIM_DIAG_DEVICES = ("/dev/i2c-1", "/dev/gpiochip0", "/dev/spidev0.0")
AGP_ETC_DIR = "/etc/agentcockpit"
AGP_HARDWARE_DIR = f"{AGP_ETC_DIR}/hardware"
AGP_SBIN_DIR = "/usr/local/sbin"
AGP_LIB_DIR = "/usr/local/lib/agentcockpit"
AGP_RUN_DIR = "/run/agentcockpit"
AGP_HW_SIM_SOCK = f"{AGP_RUN_DIR}/hw_sim.sock"
AGP_BRIDGE_DIR = f"{AGP_LIB_DIR}/web-bridge"
AGP_BRIDGE_START = f"{AGP_SBIN_DIR}/agp-bridge-start"
AGP_GPIO_SIM_START = f"{AGP_SBIN_DIR}/agp-gpio-sim-start"
AGP_GPIO_SIM_STOP = f"{AGP_SBIN_DIR}/agp-gpio-sim-stop"
AGP_CUSE_I2C = f"{AGP_SBIN_DIR}/cuse_i2c"
AGP_CUSE_SPI = f"{AGP_SBIN_DIR}/cuse_spi"
SIM_GPIO_SIM_CHECK_COMMAND = (
    'echo "@@KERNEL@@"; '
    "uname -r; "
    'echo "@@MODINFO@@"; '
    'if modinfo gpio-sim >/tmp/agp-gpio-sim.modinfo 2>/tmp/agp-gpio-sim.modinfo.err; then '
    'echo "1"; '
    'for f in filename name description depends; do '
    'v=$(modinfo -F "$f" gpio-sim 2>/dev/null || true); '
    'echo "$f: $v"; '
    "done; "
    "else echo \"0\"; cat /tmp/agp-gpio-sim.modinfo.err; fi; "
    'echo "@@CONFIG@@"; '
    'if zcat /proc/config.gz 2>/dev/null | grep -i GPIO_SIM; then true; '
    'elif grep -i GPIO_SIM /boot/config-$(uname -r) 2>/dev/null; then true; '
    'else echo "CONFIG_GPIO_SIM=(not found)"; fi; '
    'echo "@@CONFIGFS@@"; '
    'if [ -d /sys/kernel/config ]; then echo "1"; else echo "0"; fi; '
    'echo "@@DEV@@"; '
    "ls -1 /dev/gpiochip* 2>/dev/null || true"
)


def _csv_rows_for(kind: str, hw_definition: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    rows = hw_definition.get(kind, [])
    return rows if isinstance(rows, list) else []


def _devname(dev: str) -> str:
    return dev.removeprefix("/dev/")


def _unique_nonempty(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _gpio_label(row: dict[str, str], line: int) -> str:
    role = row.get("role", "").strip().lower()
    if role == "button":
        prefix = "BTN"
    elif role == "led":
        prefix = "LED"
    else:
        prefix = (role or row.get("name", "GPIO")).upper()
    return "".join(c if c.isalnum() else "_" for c in f"{prefix}_GPIO{line}")


def _gpio_rows(hw_definition: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    rows = []
    for row in _csv_rows_for("gpio", hw_definition):
        try:
            int(row.get("line", ""))
        except ValueError:
            continue
        rows.append(row)
    return rows


def _gpiochip_path(hw_definition: dict[str, list[dict[str, str]]]) -> str:
    for row in _gpio_rows(hw_definition):
        chip = row.get("chip", "").strip()
        if chip:
            return chip
    return "/dev/gpiochip0"


def _i2c_devs(hw_definition: dict[str, list[dict[str, str]]]) -> list[str]:
    return _unique_nonempty([row.get("dev", "").strip() for row in _csv_rows_for("i2c", hw_definition)])


def _spi_devs(hw_definition: dict[str, list[dict[str, str]]]) -> list[str]:
    return _unique_nonempty([row.get("dev", "").strip() for row in _csv_rows_for("spi", hw_definition)])


def _diag_devices(hw_definition: dict[str, list[dict[str, str]]]) -> list[str]:
    return _unique_nonempty([*_i2c_devs(hw_definition), _gpiochip_path(hw_definition), *_spi_devs(hw_definition)])


def _i2c_services(hw_definition: dict[str, list[dict[str, str]]]) -> list[str]:
    return [f"agp-cuse-i2c@{_devname(dev)}.service" for dev in (_i2c_devs(hw_definition) or ["/dev/i2c-1"])]


def _spi_services(hw_definition: dict[str, list[dict[str, str]]]) -> list[str]:
    return [f"agp-cuse-spi@{_devname(dev)}.service" for dev in (_spi_devs(hw_definition) or ["/dev/spidev0.0"])]


def _runtime_services(hw_definition: dict[str, list[dict[str, str]]]) -> list[str]:
    return [
        "agp-gpio-sim.service",
        "agp-bridge.service",
        *_i2c_services(hw_definition),
        *_spi_services(hw_definition),
    ]


def _sudo_write_file_command(
    path: str,
    content: str,
    *,
    mode: str | None = None,
    expand_remote_home: bool = False,
) -> str:
    command = f"printf %s {shlex.quote(content)}"
    if expand_remote_home:
        command += ' | sed "s#__AGP_HOME__#$HOME#g"'
    command += f" | sudo tee {shlex.quote(path)} >/dev/null"
    if mode:
        command += f"; sudo chmod {shlex.quote(mode)} {shlex.quote(path)}"
    return command


def gpio_sim_plan(hw_definition: dict[str, list[dict[str, str]]] | None = None) -> dict:
    hw = hw_definition or load_hw_definition()
    rows = _gpio_rows(hw)
    max_line = max([int(row["line"]) for row in rows], default=53)
    lines = []
    for row in rows:
        line = int(row["line"])
        lines.append(
            {
                "line": line,
                "label": _gpio_label(row, line),
                "direction": row.get("direction", ""),
                "role": row.get("role", ""),
                "sim_control": row.get("sim_control", ""),
            }
        )
    return {
        "driver": "gpio-sim",
        "chip": "agp",
        "label": "AgentCockpit",
        "target_device": _gpiochip_path(hw),
        "num_lines": max(max_line + 1, 54),
        "lines": lines,
        "service": "agp-gpio-sim.service",
        "start_script": AGP_GPIO_SIM_START,
        "stop_script": AGP_GPIO_SIM_STOP,
    }


def _hardware_csv_install_commands(hw_definition: dict[str, list[dict[str, str]]]) -> list[str]:
    commands = [f"sudo mkdir -p {shlex.quote(AGP_HARDWARE_DIR)}"]
    for name, rows in hw_definition.items():
        if not isinstance(rows, list) or not rows:
            continue
        fieldnames = list(rows[0].keys())
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
        content = output.getvalue()
        commands.append(_sudo_write_file_command(f"{AGP_HARDWARE_DIR}/{name}.csv", content, mode="0644"))
    return commands
































def run_sim_diag_json(host: str) -> int:
    """Run ``agp sim env diag --json``: print structured JSON, exit 0 when ok."""
    provider = _get_sim_provider()
    result = provider.run_remote(host, build_sim_diag_json_command(), capture_output=True, text=True, check=False)
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


def run_gpio_sim_check(host: str, *, json_output: bool = False) -> int:
    """Probe whether the remote simulation host can use the kernel gpio-sim."""
    provider = _get_sim_provider()
    result = provider.run_remote(host, SIM_GPIO_SIM_CHECK_COMMAND, capture_output=json_output, text=True, check=False)
    if not json_output:
        return result.returncode

    if result.returncode != 0:
        payload = {
            "kernel": None,
            "module_available": False,
            "modinfo": [],
            "config": [],
            "config_mentions_gpio_sim": False,
            "configfs_available": False,
            "gpiochips": [],
            "ok": False,
            "error": f"ssh exited {result.returncode}",
            "stderr": result.stderr.strip(),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return result.returncode

    payload = parse_gpio_sim_check(result.stdout)
    payload["host"] = host
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


def run_sim_gpio_command(
    command: str,
    *,
    host: str | None = None,
    json_output: bool = False,
) -> int:
    hw_definition = load_hw_definition()
    if command == "plan":
        payload = gpio_sim_plan(hw_definition)
        if json_output:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"Driver:  {payload['driver']}")
            print(f"Device:  {payload['target_device']}")
            print(f"Lines:   {payload['num_lines']}")
            print(f"Service: {payload['service']}")
            for line in payload["lines"]:
                print(
                    f"  GPIO{line['line']}: {line['label']} "
                    f"{line['direction']} {line['role']} {line['sim_control']}".rstrip()
                )
        return 0

    resolved_host = host or default_ec2_host(load_config())
    provider = _get_sim_provider()
    if command == "install":
        remote_command = build_gpio_systemd_install_command(hw_definition)
        result = provider.run_remote(resolved_host, remote_command, check=False)
        return result.returncode
    if command == "start":
        remote_command = (
            build_gpio_systemd_install_command(hw_definition)
            + "; sudo systemctl restart agp-gpio-sim.service; "
            + "sudo systemctl --no-pager --full status agp-gpio-sim.service"
        )
        result = provider.run_remote(resolved_host, remote_command, check=False)
        return result.returncode
    if command == "stop":
        result = provider.run_remote(
            resolved_host,
            "sudo systemctl stop agp-gpio-sim.service",
            check=False,
        )
        return result.returncode
    if command == "status":
        result = provider.run_remote(
            resolved_host,
            build_gpio_runtime_status_command(hw_definition),
            check=False,
            capture_output=json_output,
            text=True,
        )
        if not json_output:
            return result.returncode
        if result.returncode != 0:
            payload = {"ok": False, "error": f"ssh exited {result.returncode}", "stderr": result.stderr.strip()}
        else:
            payload = parse_gpio_runtime_status(result.stdout)
            payload["host"] = resolved_host
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return result.returncode if result.returncode != 0 else (0 if payload["ok"] else 1)

    print(f"unknown sim gpio command: {command}", file=sys.stderr)
    return 1


PANEL_BASE_URL = "http://127.0.0.1:8080"




def run_sim_panel(
    action: str,
    *,
    host: str | None = None,
    json_output: bool = False,
    **params,
) -> int:
    """Drive the virtual panel / display over SSH by calling the bridge API."""
    resolved_host = host or default_ec2_host(load_config())
    command = build_panel_command(action, params)
    provider = _get_sim_provider()

    if action == "state":
        result = provider.run_remote(
            resolved_host,
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(result.stderr.strip(), file=sys.stderr)
            return result.returncode
        raw = result.stdout.strip()
        if json_output:
            print(raw)
        else:
            try:
                print(json.dumps(json.loads(raw), ensure_ascii=False, indent=2))
            except json.JSONDecodeError:
                print(raw)
        return 0

    return provider.run_remote(resolved_host, command, check=False).returncode


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
    hw_definition = load_hw_definition()
    commands = {
        "start": build_sim_start_command(hw_definition),
        "stop": build_sim_stop_command(hw_definition),
        "diag": build_sim_status_command(hw_definition),
        "log": build_sim_log_command(),
    }

    if command == "status":
        resolved_host = host or default_ec2_host(load_config())
        if json_output:
            return run_sim_panel("state", host=resolved_host, json_output=True)
        port_forward_result = status_sim_port_forward(resolved_host)
        state_result = show_sim_state(resolved_host)
        return port_forward_result or state_result

    if command == "diag" and json_output:
        resolved_host = host or default_ec2_host(load_config())
        return run_sim_diag_json(resolved_host)

    if command == "gpio-sim-check":
        resolved_host = host or default_ec2_host(load_config())
        return run_gpio_sim_check(resolved_host, json_output=json_output)

    remote_command = commands.get(command)
    if remote_command is None:
        print(f"unknown sim command: {command}", file=sys.stderr)
        return 1

    resolved_host = host or default_ec2_host(load_config())

    provider = _get_sim_provider()
    result = provider.run_remote(resolved_host, remote_command, check=False)
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
    provider = _get_sim_provider()
    try:
        return provider.start_port_forward(host)
    except NotImplementedError:
        print(f"Port forwarding is not supported by provider {provider.display_name}", file=sys.stderr)
        return 1


def stop_sim_port_forward(host: str) -> int:
    provider = _get_sim_provider()
    try:
        return provider.stop_port_forward(host)
    except NotImplementedError:
        print(f"Port forwarding is not supported by provider {provider.display_name}", file=sys.stderr)
        return 1


def status_sim_port_forward(host: str) -> int:
    provider = _get_sim_provider()
    try:
        return provider.status_port_forward(host)
    except NotImplementedError:
        print(f"Port forwarding is not supported by provider {provider.display_name}", file=sys.stderr)
        return 1


def show_sim_state(host: str) -> int:
    print("--- bridge state ---")
    provider = _get_sim_provider()
    return provider.run_remote(
        host,
        "curl -s http://127.0.0.1:8080/api/state",
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
    provider = _get_sim_provider()
    try:
        return provider.interactive_shell_script(host)
    except NotImplementedError:
        quoted_host = shlex.quote(host)
        return f"""#!/usr/bin/env bash
set -euo pipefail

exec ssh -F "$HOME/.ssh/config" -t {quoted_host} "cd ~ && exec bash -l"
"""
