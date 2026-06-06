"""Linux simulation target implementations."""
from __future__ import annotations

import csv
import io
import json
import shlex
import sys
import textwrap
from urllib.parse import quote

from scripts.agp_lib._hw import load_hw_definition
from scripts.agp_lib._sim_parse import parse_gpio_runtime_status, parse_gpio_sim_check, parse_sim_diag
from scripts.agp_lib.environments.base import DevEnvironment
from scripts.agp_lib.sim.base import SimCommandBuilder, SimProvider

# Linux constants
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
PANEL_BASE_URL = "http://127.0.0.1:8080"

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

# Helpers
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

def _sudo_write_file_command(path: str, content: str, *, mode: str | None = None, expand_remote_home: bool = False) -> str:
    command = f"printf %s {shlex.quote(content)}"
    if expand_remote_home:
        command += ' | sed "s#__AGP_HOME__#$HOME#g"'
    command += f" | sudo tee {shlex.quote(path)} >/dev/null"
    if mode:
        command += f"; sudo chmod {shlex.quote(mode)} {shlex.quote(path)}"
    return command

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

def gpio_sim_plan(hw_definition: dict[str, list[dict[str, str]]] | None = None) -> dict:
    hw = hw_definition or load_hw_definition()
    rows = _gpio_rows(hw)
    max_line = max([int(row["line"]) for row in rows], default=53)
    lines = []
    for row in rows:
        line = int(row["line"])
        lines.append({
            "line": line,
            "label": _gpio_label(row, line),
            "direction": row.get("direction", ""),
            "role": row.get("role", ""),
            "sim_control": row.get("sim_control", ""),
        })
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


class LinuxSimCommandBuilder(SimCommandBuilder):
    """Generates shell commands for Linux/systemd target."""

    def build_gpio_systemd_install(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        hw = hw_definition or load_hw_definition()
        gpio_start_script = "#!/bin/sh\n" + self.build_gpio_sim_setup(hw) + "\n"
        gpio_stop_script = "#!/bin/sh\n" + self.build_gpio_sim_teardown(hw) + "\n"
        gpio_unit = textwrap.dedent(
            f"""
            [Unit]
            Description=AgentCockpit gpio-sim runtime

            [Service]
            Type=oneshot
            RemainAfterExit=yes
            RuntimeDirectory=agentcockpit
            Environment=AGP_RUNTIME_DIR={AGP_RUN_DIR}
            Environment=AGP_HW_SIM_SOCK={AGP_HW_SIM_SOCK}
            Environment=AGP_HARDWARE_DIR={AGP_HARDWARE_DIR}
            ExecStart={AGP_GPIO_SIM_START}
            ExecStop={AGP_GPIO_SIM_STOP}

            [Install]
            WantedBy=multi-user.target
            """
        ).lstrip()
        commands = [
            f"sudo mkdir -p {shlex.quote(AGP_ETC_DIR)} {shlex.quote(AGP_SBIN_DIR)}",
            *_hardware_csv_install_commands(hw),
            _sudo_write_file_command(AGP_GPIO_SIM_START, gpio_start_script, mode="0755"),
            _sudo_write_file_command(AGP_GPIO_SIM_STOP, gpio_stop_script, mode="0755"),
            _sudo_write_file_command("/etc/systemd/system/agp-gpio-sim.service", gpio_unit),
            "sudo systemctl daemon-reload",
        ]
        return "; ".join(commands)

    def build_sim_diag_json(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        hw = hw_definition or load_hw_definition()
        devices = _diag_devices(hw) or list(SIM_DIAG_DEVICES)
        return (
            'echo "@@PROC@@"; '
            'pgrep -af "bridge.py|cuse_i2c|cuse_spi" || true; '
            'echo "@@DEV@@"; '
            "for d in " + " ".join(shlex.quote(dev) for dev in devices) + "; do "
            'if [ -e "$d" ]; then echo "$d 1"; else echo "$d 0"; fi; done; '
            'echo "@@API@@"; '
            "curl -s http://127.0.0.1:8080/api/state || true"
        )

    def build_gpio_sim_setup(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        from pathlib import Path
        hw = hw_definition or load_hw_definition()
        rows = _gpio_rows(hw)
        gpiochip_path = _gpiochip_path(hw)
        gpiochip_name = Path(gpiochip_path).name
        max_line = max([int(row["line"]) for row in rows], default=53)
        num_lines = max(max_line + 1, 54)
        line_setup = []
        pull_chmod = []
        for row in rows:
            line = int(row["line"])
            label = _gpio_label(row, line)
            line_setup.append(
                f'mkdir "$base/$chip/bank0/line{line}"\n'
                f'      echo {shlex.quote(label)} > "$base/$chip/bank0/line{line}/name"'
            )
            if row.get("direction", "").lower() == "input" or row.get("sim_control", "").lower() == "pull":
                pull_chmod.append(
                    f'find /sys/devices/platform -path "*/$sim_chip/sim_gpio{line}/pull" '
                    r"-exec chmod 666 {} \; 2>/dev/null || true"
                )

        line_setup_text = "\n      ".join(line_setup) if line_setup else ":"
        pull_chmod_text = "\n      ".join(pull_chmod) if pull_chmod else ":"

        return textwrap.dedent(
            f"""
            set -eu

            sudo modprobe gpio-sim
            sudo mount -t configfs none /sys/kernel/config 2>/dev/null || true

            sudo sh -c '
              set -eu
              base=/sys/kernel/config/gpio-sim
              chip=agp

              if mountpoint -q {shlex.quote(gpiochip_path)}; then
                umount -l {shlex.quote(gpiochip_path)} || true
              fi
              if [ ! -e {shlex.quote(gpiochip_path)} ]; then
                : > {shlex.quote(gpiochip_path)}
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
              echo {num_lines} > "$base/$chip/bank0/num_lines"
              echo AgentCockpit > "$base/$chip/bank0/label"

              {line_setup_text}

              echo 1 > "$base/$chip/live"
              sim_chip=$(cat "$base/$chip/bank0/chip_name")
              chmod 666 "/dev/$sim_chip"
              {pull_chmod_text}

              if [ "$sim_chip" != {shlex.quote(gpiochip_name)} ]; then
                if [ ! -e {shlex.quote(gpiochip_path)} ]; then
                  : > {shlex.quote(gpiochip_path)}
                fi
                mount --bind "/dev/$sim_chip" {shlex.quote(gpiochip_path)}
              fi
              chmod 666 {shlex.quote(gpiochip_path)}
              echo "gpio-sim ready: {gpiochip_path} -> /dev/$sim_chip"
            '
            """
        ).strip()

    def build_gpio_sim_teardown(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        hw = hw_definition or load_hw_definition()
        gpiochip_path = _gpiochip_path(hw)
        return textwrap.dedent(
            f"""
            sudo sh -c '
              set -u
              base=/sys/kernel/config/gpio-sim
              chip=agp

              if mountpoint -q {shlex.quote(gpiochip_path)}; then
                umount -l {shlex.quote(gpiochip_path)} || true
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

    def build_systemd_install(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        hw = hw_definition or load_hw_definition()
        services = _runtime_services(hw)

        bridge_start_script = textwrap.dedent(
            f"""
            #!/bin/sh
            set -eu

            export AGP_RUNTIME_DIR="${{AGP_RUNTIME_DIR:-{AGP_RUN_DIR}}}"
            export AGP_HW_SIM_SOCK="${{AGP_HW_SIM_SOCK:-{AGP_HW_SIM_SOCK}}}"
            export AGP_HARDWARE_DIR="${{AGP_HARDWARE_DIR:-{AGP_HARDWARE_DIR}}}"

            for candidate in \\
              "${{AGP_BRIDGE_PYTHON:-}}" \\
              "{AGP_LIB_DIR}/venv/bin/python3" \\
              "/home/ubuntu/venv/bin/python3" \\
              "/home/user/venv/bin/python3" \\
              "/usr/bin/python3"
            do
              if [ -n "$candidate" ] && [ -x "$candidate" ]; then
                exec "$candidate" "{AGP_BRIDGE_DIR}/bridge.py"
              fi
            done

            echo "agp-bridge-start: no usable python3 found" >&2
            exit 1
            """
        ).lstrip()
        bridge_unit = textwrap.dedent(
            f"""
            [Unit]
            Description=AgentCockpit hardware bridge
            After=agp-gpio-sim.service
            Wants=agp-gpio-sim.service

            [Service]
            Type=simple
            RuntimeDirectory=agentcockpit
            Environment=AGP_RUNTIME_DIR={AGP_RUN_DIR}
            Environment=AGP_HW_SIM_SOCK={AGP_HW_SIM_SOCK}
            Environment=AGP_HARDWARE_DIR={AGP_HARDWARE_DIR}
            ExecStart={AGP_BRIDGE_START}
            Restart=on-failure
            RestartSec=1

            [Install]
            WantedBy=multi-user.target
            """
        ).lstrip()
        i2c_unit = textwrap.dedent(
            f"""
            [Unit]
            Description=AgentCockpit CUSE I2C runtime for %i
            After=agp-bridge.service
            Wants=agp-bridge.service

            [Service]
            Type=simple
            RuntimeDirectory=agentcockpit
            Environment=AGP_RUNTIME_DIR={AGP_RUN_DIR}
            Environment=AGP_HW_SIM_SOCK={AGP_HW_SIM_SOCK}
            Environment=AGP_HARDWARE_DIR={AGP_HARDWARE_DIR}
            ExecStart={AGP_CUSE_I2C} -f --devname=%i
            ExecStartPost=/bin/sh -c 'for n in $(seq 1 30); do [ -e /dev/%i ] && chmod 666 /dev/%i && exit 0; sleep 0.1; done; exit 0'
            Restart=on-failure
            RestartSec=1

            [Install]
            WantedBy=multi-user.target
            """
        ).lstrip()
        spi_unit = textwrap.dedent(
            f"""
            [Unit]
            Description=AgentCockpit CUSE SPI runtime for %i
            After=agp-bridge.service
            Wants=agp-bridge.service

            [Service]
            Type=simple
            RuntimeDirectory=agentcockpit
            Environment=AGP_RUNTIME_DIR={AGP_RUN_DIR}
            Environment=AGP_HW_SIM_SOCK={AGP_HW_SIM_SOCK}
            Environment=AGP_HARDWARE_DIR={AGP_HARDWARE_DIR}
            ExecStart={AGP_CUSE_SPI} -f --devname=%i
            ExecStartPost=/bin/sh -c 'for n in $(seq 1 30); do [ -e /dev/%i ] && chmod 666 /dev/%i && exit 0; sleep 0.1; done; exit 0'
            Restart=on-failure
            RestartSec=1

            [Install]
            WantedBy=multi-user.target
            """
        ).lstrip()
        target_unit = textwrap.dedent(
            f"""
            [Unit]
            Description=AgentCockpit simulation runtime
            Wants={" ".join(services)}
            After={" ".join(services)}

            [Install]
            WantedBy=multi-user.target
            """
        ).lstrip()

        commands = [
            f"sudo mkdir -p {shlex.quote(AGP_ETC_DIR)} {shlex.quote(AGP_LIB_DIR)} {shlex.quote(AGP_SBIN_DIR)}",
            *_hardware_csv_install_commands(hw),
            _sudo_write_file_command(AGP_GPIO_SIM_START, "#!/bin/sh\n" + self.build_gpio_sim_setup(hw) + "\n", mode="0755"),
            _sudo_write_file_command(AGP_GPIO_SIM_STOP, "#!/bin/sh\n" + self.build_gpio_sim_teardown(hw) + "\n", mode="0755"),
            _sudo_write_file_command(AGP_BRIDGE_START, bridge_start_script, mode="0755"),
            _sudo_write_file_command(
                "/etc/systemd/system/agp-gpio-sim.service",
                textwrap.dedent(
                    f"""
                    [Unit]
                    Description=AgentCockpit gpio-sim runtime

                    [Service]
                    Type=oneshot
                    RemainAfterExit=yes
                    RuntimeDirectory=agentcockpit
                    Environment=AGP_RUNTIME_DIR={AGP_RUN_DIR}
                    Environment=AGP_HW_SIM_SOCK={AGP_HW_SIM_SOCK}
                    Environment=AGP_HARDWARE_DIR={AGP_HARDWARE_DIR}
                    ExecStart={AGP_GPIO_SIM_START}
                    ExecStop={AGP_GPIO_SIM_STOP}

                    [Install]
                    WantedBy=multi-user.target
                    """
                ).lstrip(),
            ),
            _sudo_write_file_command("/etc/systemd/system/agp-bridge.service", bridge_unit),
            _sudo_write_file_command("/etc/systemd/system/agp-cuse-i2c@.service", i2c_unit),
            _sudo_write_file_command("/etc/systemd/system/agp-cuse-spi@.service", spi_unit),
            _sudo_write_file_command("/etc/systemd/system/agp-sim.target", target_unit),
            "sudo systemctl daemon-reload",
        ]
        return "; ".join(commands)

    def build_systemd_start(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        hw = hw_definition or load_hw_definition()
        services = " ".join(shlex.quote(service) for service in _runtime_services(hw))
        return (
            self.build_systemd_install(hw)
            + "; "
            + f"sudo systemctl stop agp-sim.target {services} >/dev/null 2>&1 || true; "
            + "sudo pkill -x cuse_i2c || true; "
            + "sudo pkill -x cuse_spi || true; "
            + "sudo systemctl start agp-sim.target; "
            + "sleep 3; "
            + "sudo systemctl --no-pager --full status agp-sim.target; "
            + 'pgrep -af "bridge.py|cuse_i2c|cuse_spi"'
        )

    def build_systemd_stop(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        hw = hw_definition or load_hw_definition()
        services = " ".join(shlex.quote(service) for service in reversed(_runtime_services(hw)))
        return (
            f"sudo systemctl stop agp-sim.target {services} >/dev/null 2>&1 || true; "
            "sudo pkill -x cuse_i2c || true; "
            "sudo pkill -x cuse_spi || true; "
            "pkill -f '[/]web-bridge/bridge.py' || true; "
            'echo "Simulation device runtime stopped."'
        )

    def build_sim_start(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return self.build_systemd_start(hw_definition)

    def build_sim_stop(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return self.build_systemd_stop(hw_definition)

    def build_sim_status(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        hw = hw_definition or load_hw_definition()
        return (
            'echo "--- processes ---"; '
            'pgrep -af "bridge.py|cuse_i2c|cuse_spi" || true; '
            'echo "--- devices ---"; '
            + "ls -l "
            + " ".join(shlex.quote(dev) for dev in _diag_devices(hw))
            + " 2>/dev/null || true; "
            'echo "--- api ---"; '
            "curl -s http://127.0.0.1:8080/api/state || true"
        )

    def build_sim_log(self) -> str:
        return (
            'echo "--- journalctl agp runtime ---"; '
            "journalctl --no-pager -n 120 "
            "-u agp-sim.target -u agp-gpio-sim.service -u agp-bridge.service "
            "-u 'agp-cuse-i2c@*.service' -u 'agp-cuse-spi@*.service' || true; "
            'echo "--- legacy logs ---"; '
            "tail -n 80 /tmp/bridge.log /tmp/cuse.log /tmp/cuse_spi.log 2>/dev/null || true"
        )

    def build_gpio_runtime_status(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        hw = hw_definition or load_hw_definition()
        gpiochip_path = _gpiochip_path(hw)
        return (
            'echo "@@SERVICE@@"; '
            "systemctl is-active agp-gpio-sim.service 2>/dev/null || true; "
            'echo "@@DEVICE@@"; '
            f"if [ -e {shlex.quote(gpiochip_path)} ]; then echo {shlex.quote(gpiochip_path)} 1; "
            f"else echo {shlex.quote(gpiochip_path)} 0; fi; "
            'echo "@@MOUNT@@"; '
            f"if mountpoint -q {shlex.quote(gpiochip_path)}; then echo 1; "
            f"findmnt -n -o SOURCE --target {shlex.quote(gpiochip_path)} 2>/dev/null || true; "
            "else echo 0; fi; "
            'echo "@@CONFIGFS@@"; '
            "base=/sys/kernel/config/gpio-sim/agp; "
            'if [ -d "$base" ]; then echo 1; '
            'if [ -f "$base/live" ]; then cat "$base/live"; else echo "?"; fi; '
            'if [ -f "$base/bank0/chip_name" ]; then cat "$base/bank0/chip_name"; else echo ""; fi; '
            "else echo 0; fi; "
            'echo "@@GPIOCHIPS@@"; '
            "ls -1 /dev/gpiochip* 2>/dev/null || true"
        )

    def build_panel(self, action: str, params: dict) -> str:
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


class LinuxSystemdSimProvider(SimProvider):
    def __init__(self, dev_env: DevEnvironment, host: str, builder: SimCommandBuilder):
        self.dev_env = dev_env
        self.host = host
        self.builder = builder

    def start(self, hw_definition: dict[str, list[dict[str, str]]]) -> int:
        cmd = self.builder.build_sim_start(hw_definition)
        return self.dev_env.run_remote(self.host, cmd, check=False).returncode

    def stop(self, hw_definition: dict[str, list[dict[str, str]]]) -> int:
        cmd = self.builder.build_sim_stop(hw_definition)
        return self.dev_env.run_remote(self.host, cmd, check=False).returncode

    def status(self, hw_definition: dict[str, list[dict[str, str]]], json_output: bool = False) -> int:
        if json_output:
            return self.panel("state", params={}, json_output=True)
        cmd = self.builder.build_sim_status(hw_definition)
        return self.dev_env.run_remote(self.host, cmd, check=False).returncode

    def log(self) -> int:
        cmd = self.builder.build_sim_log()
        return self.dev_env.run_remote(self.host, cmd, check=False).returncode

    def diag_json(self, hw_definition: dict[str, list[dict[str, str]]]) -> int:
        cmd = self.builder.build_sim_diag_json(hw_definition)
        result = self.dev_env.run_remote(self.host, cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            payload = {
                "processes": [], "devices": {}, "api": None, "ok": False,
                "error": f"ssh exited {result.returncode}", "stderr": result.stderr.strip()
            }
        else:
            payload = parse_sim_diag(result.stdout)
            payload["host"] = self.host
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("ok") else 1

    def gpio_sim_check(self, json_output: bool = False) -> int:
        cmd = SIM_GPIO_SIM_CHECK_COMMAND
        result = self.dev_env.run_remote(self.host, cmd, capture_output=json_output, text=True, check=False)
        if not json_output:
            return result.returncode
        if result.returncode != 0:
            payload = {"kernel": None, "module_available": False, "ok": False, "error": f"ssh exited {result.returncode}", "stderr": result.stderr.strip()}
        else:
            payload = parse_gpio_sim_check(result.stdout)
            payload["host"] = self.host
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("ok") else 1

    def gpio_command(self, command: str, hw_definition: dict[str, list[dict[str, str]]], json_output: bool = False) -> int:
        if command == "install":
            cmd = self.builder.build_gpio_systemd_install(hw_definition)
            return self.dev_env.run_remote(self.host, cmd, check=False).returncode
        if command == "start":
            cmd = self.builder.build_gpio_systemd_install(hw_definition) + "; sudo systemctl restart agp-gpio-sim.service; sudo systemctl --no-pager --full status agp-gpio-sim.service"
            return self.dev_env.run_remote(self.host, cmd, check=False).returncode
        if command == "stop":
            return self.dev_env.run_remote(self.host, "sudo systemctl stop agp-gpio-sim.service", check=False).returncode
        if command == "status":
            cmd = self.builder.build_gpio_runtime_status(hw_definition)
            result = self.dev_env.run_remote(self.host, cmd, check=False, capture_output=json_output, text=True)
            if not json_output:
                return result.returncode
            if result.returncode != 0:
                payload = {"ok": False, "error": f"ssh exited {result.returncode}", "stderr": result.stderr.strip()}
            else:
                payload = parse_gpio_runtime_status(result.stdout)
                payload["host"] = self.host
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return result.returncode if result.returncode != 0 else (0 if payload["ok"] else 1)

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

        print(f"unknown sim gpio command: {command}", file=sys.stderr)
        return 1

    def panel(self, action: str, params: dict, json_output: bool = False) -> int:
        cmd = self.builder.build_panel(action, params)
        if action == "state":
            result = self.dev_env.run_remote(self.host, cmd, check=False, capture_output=True, text=True)
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
        return self.dev_env.run_remote(self.host, cmd, check=False).returncode
