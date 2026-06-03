"""`agp sim` subcommand: simulation runtime control over SSH."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path
from urllib.parse import quote

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
    'pgrep -af "bridge.py|cuse_i2c|cuse_spi" || true; '
    'echo "@@DEV@@"; '
    "for d in " + " ".join(SIM_DIAG_DEVICES) + "; do "
    'if [ -e "$d" ]; then echo "$d 1"; else echo "$d 0"; fi; done; '
    'echo "@@API@@"; '
    "curl -s http://127.0.0.1:8080/api/state || true"
)
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

SIM_GPIO_SIM_SETUP_COMMAND = textwrap.dedent(
    r"""
    set -eu

    sudo modprobe gpio-sim
    sudo mount -t configfs none /sys/kernel/config 2>/dev/null || true

    sudo sh -c '
      set -eu
      base=/sys/kernel/config/gpio-sim
      chip=agp

      if mountpoint -q /dev/gpiochip0; then
        umount /dev/gpiochip0 || true
      fi

      if [ -d "$base/$chip" ]; then
        echo 0 > "$base/$chip/live" 2>/dev/null || true
        for bank in "$base/$chip"/*; do
          name=$(basename "$bank")
          [ "$name" = live ] && continue
          [ "$name" = dev_name ] && continue
          for line in "$bank"/line*; do
            [ -d "$line" ] && rmdir "$line" || true
          done
          rmdir "$bank" || true
        done
        rmdir "$base/$chip" || true
      fi

      mkdir "$base/$chip"
      mkdir "$base/$chip/bank0"
      echo 54 > "$base/$chip/bank0/num_lines"
      echo AgentCockpit > "$base/$chip/bank0/label"

      mkdir "$base/$chip/bank0/line17"
      echo BTN_GPIO17 > "$base/$chip/bank0/line17/name"
      mkdir "$base/$chip/bank0/line18"
      echo LED_GPIO18 > "$base/$chip/bank0/line18/name"
      mkdir "$base/$chip/bank0/line24"
      echo LED_GPIO24 > "$base/$chip/bank0/line24/name"
      mkdir "$base/$chip/bank0/line27"
      echo BTN_GPIO27 > "$base/$chip/bank0/line27/name"

      echo 1 > "$base/$chip/live"
      sim_chip=$(cat "$base/$chip/bank0/chip_name")
      chmod 666 "/dev/$sim_chip"
      find /sys/devices/platform -path "*/$sim_chip/sim_gpio17/pull" -exec chmod 666 {} \; 2>/dev/null || true
      find /sys/devices/platform -path "*/$sim_chip/sim_gpio27/pull" -exec chmod 666 {} \; 2>/dev/null || true

      if [ "$sim_chip" != gpiochip0 ]; then
        mount --bind "/dev/$sim_chip" /dev/gpiochip0
      fi
      chmod 666 /dev/gpiochip0
      echo "gpio-sim ready: /dev/gpiochip0 -> /dev/$sim_chip"
    '
    """
).strip()

SIM_GPIO_SIM_TEARDOWN_COMMAND = textwrap.dedent(
    r"""
    sudo sh -c '
      set -u
      base=/sys/kernel/config/gpio-sim
      chip=agp

      if mountpoint -q /dev/gpiochip0; then
        umount /dev/gpiochip0 || true
      fi

      if [ -d "$base/$chip" ]; then
        echo 0 > "$base/$chip/live" 2>/dev/null || true
        for bank in "$base/$chip"/*; do
          name=$(basename "$bank")
          [ "$name" = live ] && continue
          [ "$name" = dev_name ] && continue
          for line in "$bank"/line*; do
            [ -d "$line" ] && rmdir "$line" || true
          done
          rmdir "$bank" || true
        done
        rmdir "$base/$chip" || true
      fi
    '
    """
).strip()
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


def parse_gpio_sim_check(raw: str) -> dict:
    """Parse the marker-delimited gpio-sim capability probe output."""
    section = None
    sections: dict[str, list[str]] = {
        "kernel": [],
        "modinfo": [],
        "config": [],
        "configfs": [],
        "dev": [],
    }
    marker_map = {
        "@@KERNEL@@": "kernel",
        "@@MODINFO@@": "modinfo",
        "@@CONFIG@@": "config",
        "@@CONFIGFS@@": "configfs",
        "@@DEV@@": "dev",
    }
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped in marker_map:
            section = marker_map[stripped]
            continue
        if section is not None:
            sections[section].append(line)

    modinfo_lines = [line.strip() for line in sections["modinfo"] if line.strip()]
    modinfo_available = bool(modinfo_lines and modinfo_lines[0] == "1")
    modinfo = modinfo_lines[1:] if modinfo_lines else []
    config_lines = [line.strip() for line in sections["config"] if line.strip()]
    config_mentions_gpio_sim = any(
        "GPIO_SIM" in line.upper() and "(NOT FOUND)" not in line.upper()
        for line in config_lines
    )
    configfs_available = any(line.strip() == "1" for line in sections["configfs"])
    gpiochips = [line.strip() for line in sections["dev"] if line.strip()]

    return {
        "kernel": next((line.strip() for line in sections["kernel"] if line.strip()), None),
        "module_available": modinfo_available,
        "modinfo": modinfo,
        "config": config_lines,
        "config_mentions_gpio_sim": config_mentions_gpio_sim,
        "configfs_available": configfs_available,
        "gpiochips": gpiochips,
        "ok": modinfo_available or config_mentions_gpio_sim,
    }


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


def run_gpio_sim_check(host: str, *, json_output: bool = False) -> int:
    """Probe whether the remote simulation host can use the kernel gpio-sim."""
    result = subprocess.run(
        ["ssh", "-F", str(Path.home() / ".ssh" / "config"), host, SIM_GPIO_SIM_CHECK_COMMAND],
        check=False,
        capture_output=json_output,
        text=True,
    )
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


PANEL_BASE_URL = "http://127.0.0.1:8080"


def build_panel_command(action: str, params: dict) -> str:
    """Build the remote ``curl`` command for a virtual panel action.

    Pure/string-only so it can be unit-tested without SSH. Mirrors the bridge
    HTTP API served on the simulation host's ``127.0.0.1:8080``.
    """
    base = PANEL_BASE_URL
    if action == "button-press":
        line = int(params.get("line", 17))
        duration_ms = max(0, int(params.get("duration_ms", 150)))
        return f'curl -s -X POST "{base}/api/button/press?line={line}&duration_ms={duration_ms}"'
    if action == "button-set":
        line = int(params["line"])
        value = 1 if int(params.get("value", 1)) else 0
        return f'curl -s -X POST "{base}/api/button?line={line}&value={value}"'
    if action == "rfid-tap":
        uid = quote(str(params["uid"]), safe=":")
        return f'curl -s -X POST "{base}/api/rfid/tap?uid={uid}"'
    if action == "rfid-remove":
        return f'curl -s -X POST "{base}/api/rfid/remove"'
    if action == "range-set":
        value = int(params["value"])
        return f'curl -s -X POST "{base}/api/range?value={value}"'
    if action == "state":
        return f'curl -s "{base}/api/state"'
    raise ValueError(f"unknown panel action: {action}")


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
    ssh_argv = ["ssh", "-F", str(Path.home() / ".ssh" / "config"), resolved_host, command]

    if action == "state":
        result = subprocess.run(ssh_argv, check=False, capture_output=True, text=True)
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

    return subprocess.run(ssh_argv, check=False).returncode


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
            SIM_GPIO_SIM_SETUP_COMMAND
            + "; "
            'setsid bash -c "nohup ~/venv/bin/python3 ~/web-bridge/bridge.py '
            '> /tmp/bridge.log 2>&1 &" < /dev/null; '
            "sleep 2; "
            'setsid bash -c "sudo nohup ~/cuse_i2c -f --devname=i2c-1 '
            '> /tmp/cuse.log 2>&1 &" < /dev/null; '
            'setsid bash -c "sudo nohup ~/cuse_spi -f --devname=spidev0.0 '
            '> /tmp/cuse_spi.log 2>&1 &" < /dev/null; '
            "sleep 3; "
            "sudo chmod 666 /dev/i2c-1 /dev/spidev0.0; "
            'pgrep -af "bridge.py|cuse_i2c|cuse_spi"'
        ),
        "stop": (
            SIM_GPIO_SIM_TEARDOWN_COMMAND
            + "; "
            "sudo pkill -f '[c]use_i2c' || true; "
            "sudo pkill -f '[c]use_spi' || true; "
            "pkill -f '[b]ridge.py' || true; "
            'echo "Simulation device runtime stopped."'
        ),
        "diag": (
            'echo "--- processes ---"; '
            'pgrep -af "bridge.py|cuse_i2c|cuse_spi" || true; '
            'echo "--- devices ---"; '
            "ls -l /dev/i2c-1 /dev/gpiochip0 /dev/spidev0.0 2>/dev/null || true; "
            'echo "--- api ---"; '
            "curl -s http://127.0.0.1:8080/api/state || true"
        ),
        "log": (
            'echo "--- bridge.log ---"; '
            "tail -n 80 /tmp/bridge.log 2>/dev/null; "
            'echo "--- cuse.log ---"; '
            "tail -n 80 /tmp/cuse.log 2>/dev/null; "
            'echo "--- cuse_spi.log ---"; '
            "tail -n 80 /tmp/cuse_spi.log 2>/dev/null"
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

    if command == "gpio-sim-check":
        resolved_host = host or default_ec2_host(load_config())
        return run_gpio_sim_check(resolved_host, json_output=json_output)

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
