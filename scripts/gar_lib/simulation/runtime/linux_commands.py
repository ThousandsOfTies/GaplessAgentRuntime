"""Linux/systemd simulation command construction and GPIO planning."""

from __future__ import annotations

import csv
import io
import json
import shlex
import textwrap
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlencode

from scripts.gar_lib.simulation.hardware import io_actions
from scripts.gar_lib.simulation.runtime.deployment import remote_identity_command

# Linux constants
SIM_DIAG_DEVICES = ("/dev/i2c-1", "/dev/gpiochip0", "/dev/spidev0.0")
GAR_ETC_DIR = "/etc/gar"
GAR_HARDWARE_DIR = f"{GAR_ETC_DIR}/hardware"
GAR_SBIN_DIR = "/usr/local/sbin"
GAR_LIB_DIR = "/usr/local/lib/gar"
GAR_RUN_DIR = "/run/gar"
GAR_METRICS_DIR = f"{GAR_RUN_DIR}/metrics"
GAR_HW_SIM_SOCK = f"{GAR_RUN_DIR}/hw_sim.sock"
GAR_BRIDGE_DIR = f"{GAR_LIB_DIR}/web-bridge"
GAR_BRIDGE_START = f"{GAR_SBIN_DIR}/gar-bridge-start"
GAR_GPIO_SIM_START = f"{GAR_SBIN_DIR}/gar-gpio-sim-start"
GAR_GPIO_SIM_STOP = f"{GAR_SBIN_DIR}/gar-gpio-sim-stop"
GAR_CUSE_I2C = f"{GAR_SBIN_DIR}/cuse_i2c"
GAR_CUSE_SPI = f"{GAR_SBIN_DIR}/cuse_spi"
GAR_V4L2_CAMERA_SERVICE = "gar-v4l2-camera.service"
GAR_SIM_APP_SERVICE = "gar-sim-app.service"
PANEL_BASE_URL = "http://127.0.0.1:8080"
CURL_OPTIONS = "--silent --show-error --fail --connect-timeout 2 --max-time 5"
SIM_RUNTIME_PROCESS_PATTERN = "[b]ridge.py|[c]use_i2c|[c]use_spi|[c]amera_tx.py|[v]ideo_monitor.py|[g]st-launch-1.0"

SIM_GPIO_SIM_CHECK_COMMAND = (
    'echo "@@KERNEL@@"; '
    "uname -r; "
    'echo "@@MODINFO@@"; '
    "if modinfo gpio-sim >/tmp/gar-gpio-sim.modinfo 2>/tmp/gar-gpio-sim.modinfo.err; then "
    'echo "1"; '
    "for f in filename name description depends; do "
    'v=$(modinfo -F "$f" gpio-sim 2>/dev/null || true); '
    'echo "$f: $v"; '
    "done; "
    'else echo "0"; cat /tmp/gar-gpio-sim.modinfo.err; fi; '
    'echo "@@CONFIG@@"; '
    "if zcat /proc/config.gz 2>/dev/null | grep -i GPIO_SIM; then true; "
    "elif grep -i GPIO_SIM /boot/config-$(uname -r) 2>/dev/null; then true; "
    'else echo "CONFIG_GPIO_SIM=(not found)"; fi; '
    'echo "@@CONFIGFS@@"; '
    'if [ -d /sys/kernel/config ]; then echo "1"; else echo "0"; fi; '
    'echo "@@DEV@@"; '
    "ls -1 /dev/gpiochip* 2>/dev/null || true"
)


# Helpers
def _fail_fast_script(steps: Sequence[str]) -> str:
    """Render named lifecycle steps as one shell script that stops at first failure."""

    return "set -eu\n" + "\n".join(steps)


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
    return _unique_nonempty(
        [row.get("dev", "").strip() for row in _csv_rows_for("i2c", hw_definition) if row.get("sim", "").strip()]
    )


def _spi_devs(hw_definition: dict[str, list[dict[str, str]]]) -> list[str]:
    return _unique_nonempty(
        [row.get("dev", "").strip() for row in _csv_rows_for("spi", hw_definition) if row.get("sim", "").strip()]
    )


def _video_devs(hw_definition: dict[str, list[dict[str, str]]]) -> list[str]:
    return _unique_nonempty(
        [row.get("dev", "").strip() for row in _csv_rows_for("video", hw_definition) if row.get("sim", "").strip()]
    )


def _diag_devices(hw_definition: dict[str, list[dict[str, str]]]) -> list[str]:
    return _unique_nonempty(
        [
            *_i2c_devs(hw_definition),
            _gpiochip_path(hw_definition),
            *_spi_devs(hw_definition),
            *_video_devs(hw_definition),
        ]
    )


def _i2c_services(hw_definition: dict[str, list[dict[str, str]]]) -> list[str]:
    return [
        f"gar-cuse-i2c@{_devname(dev)}.service"
        for dev in _simulated_devs_or_legacy_default(
            hw_definition,
            _i2c_devs(hw_definition),
            "/dev/i2c-1",
        )
    ]


def _spi_services(hw_definition: dict[str, list[dict[str, str]]]) -> list[str]:
    return [
        f"gar-cuse-spi@{_devname(dev)}.service"
        for dev in _simulated_devs_or_legacy_default(
            hw_definition,
            _spi_devs(hw_definition),
            "/dev/spidev0.0",
        )
    ]


def _simulated_devs_or_legacy_default(
    hw_definition: dict[str, list[dict[str, str]]],
    devices: list[str],
    default: str,
) -> list[str]:
    """Keep the old defaults only when no hardware rows exist at all."""

    if devices:
        return devices
    if any(_csv_rows_for(kind, hw_definition) for kind in ("gpio", "i2c", "spi", "video")):
        return []
    return [default]


def _spi_service_options(hw_definition: dict[str, list[dict[str, str]]]) -> str:
    """Return options required by the selected SPI simulator implementation."""

    simulated_drivers = {row.get("sim", "").strip().lower() for row in _csv_rows_for("spi", hw_definition)}
    if "ili9341" not in simulated_drivers:
        return ""

    for row in _gpio_rows(hw_definition):
        name = row.get("name", "").strip().lower()
        role = row.get("role", "").strip().lower()
        if name in {"lcd_dc", "display_dc"} or (role == "display_ctrl" and name.endswith("_dc")):
            return f" --dc-line={int(row['line'])}"
    return ""


def _runtime_services(hw_definition: dict[str, list[dict[str, str]]]) -> list[str]:
    video_services = [GAR_V4L2_CAMERA_SERVICE] if _video_devs(hw_definition) else []
    return [
        "gar-gpio-sim.service",
        "gar-bridge.service",
        *video_services,
        *_i2c_services(hw_definition),
        *_spi_services(hw_definition),
        GAR_SIM_APP_SERVICE,
    ]


def _sudo_write_file_command(
    path: str, content: str, *, mode: str | None = None, expand_remote_home: bool = False
) -> str:
    command = f"printf %s {shlex.quote(content)}"
    if expand_remote_home:
        command += ' | sed "s#__GAR_HOME__#$HOME#g"'
    command += f" | sudo tee {shlex.quote(path)} >/dev/null"
    if mode:
        command += f"\nsudo chmod {shlex.quote(mode)} {shlex.quote(path)}"
    return command


def _hardware_csv_install_commands(hw_definition: dict[str, list[dict[str, str]]]) -> list[str]:
    commands = [
        f"sudo mkdir -p {shlex.quote(GAR_HARDWARE_DIR)}",
        f"sudo rm -f {shlex.quote(GAR_HARDWARE_DIR)}/*.csv",
    ]
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
        commands.append(_sudo_write_file_command(f"{GAR_HARDWARE_DIR}/{name}.csv", content, mode="0644"))
    return commands


def gpio_sim_plan(hw_definition: dict[str, list[dict[str, str]]]) -> dict[str, object]:
    hw = hw_definition
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
        "chip": "gar",
        "label": "Gapless Agent Runtime",
        "target_device": _gpiochip_path(hw),
        "num_lines": max(max_line + 1, 54),
        "lines": lines,
        "service": "gar-gpio-sim.service",
        "start_script": GAR_GPIO_SIM_START,
        "stop_script": GAR_GPIO_SIM_STOP,
    }


class LinuxSystemdCommandBuilder:
    """Generates shell commands for Linux/systemd target."""

    def build_gpio_systemd_install(self, hw_definition: dict[str, list[dict[str, str]]]) -> str:
        hw = hw_definition
        gpio_start_script = "#!/bin/sh\n" + self.build_gpio_sim_setup(hw) + "\n"
        gpio_stop_script = "#!/bin/sh\n" + self.build_gpio_sim_teardown(hw) + "\n"
        gpio_unit = textwrap.dedent(
            f"""
            [Unit]
            Description=Gapless Agent Runtime gpio-sim runtime

            [Service]
            Type=oneshot
            RemainAfterExit=yes
            RuntimeDirectory=gar
            Environment=GAR_RUNTIME_DIR={GAR_RUN_DIR}
            Environment=GAR_HW_SIM_SOCK={GAR_HW_SIM_SOCK}
            Environment=GAR_HARDWARE_DIR={GAR_HARDWARE_DIR}
            ExecStart={GAR_GPIO_SIM_START}
            ExecStop={GAR_GPIO_SIM_STOP}

            [Install]
            WantedBy=multi-user.target
            """
        ).lstrip()
        commands = [
            f"sudo mkdir -p {shlex.quote(GAR_ETC_DIR)} {shlex.quote(GAR_SBIN_DIR)}",
            *_hardware_csv_install_commands(hw),
            _sudo_write_file_command(GAR_GPIO_SIM_START, gpio_start_script, mode="0755"),
            _sudo_write_file_command(GAR_GPIO_SIM_STOP, gpio_stop_script, mode="0755"),
            _sudo_write_file_command("/etc/systemd/system/gar-gpio-sim.service", gpio_unit),
            "sudo systemctl daemon-reload",
        ]
        return _fail_fast_script(commands)

    def build_gpio_systemd_start(self, hw_definition: dict[str, list[dict[str, str]]]) -> str:
        install_service = self.build_gpio_systemd_install(hw_definition)
        restart_service = "sudo systemctl restart gar-gpio-sim.service"
        verify_service = "sudo systemctl --no-pager --full status gar-gpio-sim.service"
        return _fail_fast_script(
            (
                install_service,
                restart_service,
                verify_service,
            )
        )

    def build_sim_diag_json(self, hw_definition: dict[str, list[dict[str, str]]]) -> str:
        hw = hw_definition
        devices = _diag_devices(hw) or list(SIM_DIAG_DEVICES)
        return (
            'echo "@@PROC@@"; '
            f'pgrep -af "{SIM_RUNTIME_PROCESS_PATTERN}" || true; '
            'echo "@@DEV@@"; '
            "for d in " + " ".join(shlex.quote(dev) for dev in devices) + "; do "
            'if [ -e "$d" ]; then echo "$d 1"; else echo "$d 0"; fi; done; '
            'echo "@@API@@"; '
            f"curl {CURL_OPTIONS} http://127.0.0.1:8080/api/state || true"
        )

    def build_gpio_sim_setup(self, hw_definition: dict[str, list[dict[str, str]]]) -> str:
        from pathlib import Path

        hw = hw_definition
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
              chip=gar

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
              echo Gapless Agent Runtime > "$base/$chip/bank0/label"

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

    def build_gpio_sim_teardown(self, hw_definition: dict[str, list[dict[str, str]]]) -> str:
        hw = hw_definition
        gpiochip_path = _gpiochip_path(hw)
        return textwrap.dedent(
            f"""
            sudo sh -c '
              set -u
              base=/sys/kernel/config/gpio-sim
              chip=gar

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

    def build_systemd_install(self, hw_definition: dict[str, list[dict[str, str]]]) -> str:
        hw = hw_definition
        services = _runtime_services(hw)
        spi_service_options = _spi_service_options(hw)

        bridge_start_script = textwrap.dedent(
            f"""
            #!/bin/sh
            set -eu

            export GAR_RUNTIME_DIR="${{GAR_RUNTIME_DIR:-{GAR_RUN_DIR}}}"
            export GAR_METRICS_DIR="${{GAR_METRICS_DIR:-{GAR_METRICS_DIR}}}"
            export GAR_HW_SIM_SOCK="${{GAR_HW_SIM_SOCK:-{GAR_HW_SIM_SOCK}}}"
            export GAR_HARDWARE_DIR="${{GAR_HARDWARE_DIR:-{GAR_HARDWARE_DIR}}}"

            for candidate in \\
              "${{GAR_BRIDGE_PYTHON:-}}" \\
              "{GAR_LIB_DIR}/venv/bin/python3" \\
              "/home/ubuntu/venv/bin/python3" \\
              "/home/user/venv/bin/python3" \\
              "/usr/bin/python3"
            do
              if [ -n "$candidate" ] && [ -x "$candidate" ] && \
                 "$candidate" -c 'import aiohttp' >/dev/null 2>&1; then
                exec "$candidate" "{GAR_BRIDGE_DIR}/bridge.py"
              fi
            done

            echo "gar-bridge-start: no python3 with aiohttp found" >&2
            echo "install python3-aiohttp or deploy {GAR_LIB_DIR}/venv" >&2
            exit 1
            """
        ).lstrip()
        bridge_unit = textwrap.dedent(
            f"""
            [Unit]
            Description=Gapless Agent Runtime hardware bridge
            After=gar-gpio-sim.service
            Wants=gar-gpio-sim.service

            [Service]
            Type=simple
            RuntimeDirectory=gar
            Environment=GAR_RUNTIME_DIR={GAR_RUN_DIR}
            Environment=GAR_METRICS_DIR={GAR_METRICS_DIR}
            Environment=GAR_HW_SIM_SOCK={GAR_HW_SIM_SOCK}
            Environment=GAR_HARDWARE_DIR={GAR_HARDWARE_DIR}
            ExecStartPre=/bin/mkdir -p {GAR_METRICS_DIR}
            PassEnvironment=GAR_BRIDGE_HOST GAR_BRIDGE_PORT GAR_BRIDGE_ALLOWED_HOSTS GAR_CAMERA_DEVICE GAR_CAMERA_WIDTH GAR_CAMERA_HEIGHT GAR_CAMERA_FPS
            ExecStart={GAR_BRIDGE_START}
            Restart=on-failure
            RestartSec=1

            [Install]
            WantedBy=multi-user.target
            """
        ).lstrip()
        i2c_unit = textwrap.dedent(
            f"""
            [Unit]
            Description=Gapless Agent Runtime CUSE I2C runtime for %i
            After=gar-bridge.service
            Wants=gar-bridge.service

            [Service]
            Type=simple
            RuntimeDirectory=gar
            Environment=GAR_RUNTIME_DIR={GAR_RUN_DIR}
            Environment=GAR_HW_SIM_SOCK={GAR_HW_SIM_SOCK}
            Environment=GAR_HARDWARE_DIR={GAR_HARDWARE_DIR}
            ExecStart={GAR_CUSE_I2C} -f --devname=%i
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
            Description=Gapless Agent Runtime CUSE SPI runtime for %i
            After=gar-bridge.service
            Wants=gar-bridge.service

            [Service]
            Type=simple
            RuntimeDirectory=gar
            Environment=GAR_RUNTIME_DIR={GAR_RUN_DIR}
            Environment=GAR_HW_SIM_SOCK={GAR_HW_SIM_SOCK}
            Environment=GAR_HARDWARE_DIR={GAR_HARDWARE_DIR}
            ExecStart={GAR_CUSE_SPI} -f --devname=%i{spi_service_options}
            ExecStartPost=/bin/sh -c 'for n in $(seq 1 30); do [ -e /dev/%i ] && chmod 666 /dev/%i && exit 0; sleep 0.1; done; exit 0'
            Restart=on-failure
            RestartSec=1

            [Install]
            WantedBy=multi-user.target
            """
        ).lstrip()
        video_device = (_video_devs(hw) or ["/dev/video0"])[0]
        video_unit = textwrap.dedent(
            f"""
            [Unit]
            Description=Gapless Agent Runtime V4L2 camera input

            [Service]
            Type=oneshot
            RemainAfterExit=yes
            ExecStartPre=-/sbin/modprobe -r v4l2loopback
            ExecStart=/sbin/modprobe v4l2loopback video_nr={Path(video_device).name.removeprefix("video")} card_label=GAR_Camera exclusive_caps=0
            ExecStartPost=/bin/sh -c 'for n in $(seq 1 30); do [ -e {video_device} ] && chmod 666 {video_device} && exit 0; sleep 0.1; done; exit 1'
            ExecStop=-/sbin/modprobe -r v4l2loopback

            [Install]
            WantedBy=multi-user.target
            """
        ).lstrip()
        default_app_unit = textwrap.dedent(
            """
            [Unit]
            Description=Gapless Agent Runtime empty simulation application
            PartOf=gar-sim.target

            [Service]
            Type=oneshot
            RemainAfterExit=yes
            ExecStart=/bin/true
            """
        ).lstrip()
        app_unit_path = f"/etc/systemd/system/{GAR_SIM_APP_SERVICE}"
        install_default_app = (
            f"if [ ! -f {shlex.quote(app_unit_path)} ]; then\n"
            + _sudo_write_file_command(app_unit_path, default_app_unit)
            + "\nfi"
        )
        target_unit = textwrap.dedent(
            f"""
            [Unit]
            Description=Gapless Agent Runtime simulation runtime
            Wants={" ".join(services)}
            After={" ".join(services)}

            [Install]
            WantedBy=multi-user.target
            """
        ).lstrip()

        commands = [
            f"sudo mkdir -p {shlex.quote(GAR_ETC_DIR)} {shlex.quote(GAR_LIB_DIR)} {shlex.quote(GAR_SBIN_DIR)} {shlex.quote(GAR_METRICS_DIR)}",
            *_hardware_csv_install_commands(hw),
            _sudo_write_file_command(
                GAR_GPIO_SIM_START, "#!/bin/sh\n" + self.build_gpio_sim_setup(hw) + "\n", mode="0755"
            ),
            _sudo_write_file_command(
                GAR_GPIO_SIM_STOP, "#!/bin/sh\n" + self.build_gpio_sim_teardown(hw) + "\n", mode="0755"
            ),
            _sudo_write_file_command(GAR_BRIDGE_START, bridge_start_script, mode="0755"),
            _sudo_write_file_command(
                "/etc/systemd/system/gar-gpio-sim.service",
                textwrap.dedent(
                    f"""
                    [Unit]
                    Description=Gapless Agent Runtime gpio-sim runtime

                    [Service]
                    Type=oneshot
                    RemainAfterExit=yes
                    RuntimeDirectory=gar
                    Environment=GAR_RUNTIME_DIR={GAR_RUN_DIR}
                    Environment=GAR_HW_SIM_SOCK={GAR_HW_SIM_SOCK}
                    Environment=GAR_HARDWARE_DIR={GAR_HARDWARE_DIR}
                    ExecStart={GAR_GPIO_SIM_START}
                    ExecStop={GAR_GPIO_SIM_STOP}

                    [Install]
                    WantedBy=multi-user.target
                    """
                ).lstrip(),
            ),
            _sudo_write_file_command("/etc/systemd/system/gar-bridge.service", bridge_unit),
            _sudo_write_file_command("/etc/systemd/system/gar-cuse-i2c@.service", i2c_unit),
            _sudo_write_file_command("/etc/systemd/system/gar-cuse-spi@.service", spi_unit),
            _sudo_write_file_command(f"/etc/systemd/system/{GAR_V4L2_CAMERA_SERVICE}", video_unit),
            install_default_app,
            _sudo_write_file_command("/etc/systemd/system/gar-sim.target", target_unit),
            "sudo systemctl daemon-reload",
        ]
        return _fail_fast_script(commands)

    def build_systemd_start(self, hw_definition: dict[str, list[dict[str, str]]]) -> str:
        hw = hw_definition
        services = " ".join(shlex.quote(service) for service in _runtime_services(hw))
        install_runtime = self.build_systemd_install(hw)
        stop_previous_runtime = f"sudo systemctl stop gar-sim.target {services}"
        start_runtime = "sudo systemctl start gar-sim.target"
        show_runtime_status = "sudo systemctl --no-pager --full status gar-sim.target"
        verify_services = f"sudo systemctl is-active {services}"
        return _fail_fast_script(
            (
                install_runtime,
                stop_previous_runtime,
                start_runtime,
                "sleep 3",
                show_runtime_status,
                verify_services,
            )
        )

    def build_systemd_stop(self, hw_definition: dict[str, list[dict[str, str]]]) -> str:
        hw = hw_definition
        services = " ".join(shlex.quote(service) for service in reversed(_runtime_services(hw)))
        stop_runtime = f"sudo systemctl stop gar-sim.target {services}"
        return _fail_fast_script(
            (
                stop_runtime,
                'echo "Simulation device runtime stopped."',
            )
        )

    def build_sim_start(self, hw_definition: dict[str, list[dict[str, str]]]) -> str:
        command = self.build_systemd_start(hw_definition)
        return remote_identity_command(f"raise SystemExit(start_service({command!r}))", sudo=True)

    def build_sim_stop(self, hw_definition: dict[str, list[dict[str, str]]]) -> str:
        return self.build_systemd_stop(hw_definition)

    def build_sim_status(self, hw_definition: dict[str, list[dict[str, str]]]) -> str:
        hw = hw_definition
        return (
            'echo "--- processes ---"; '
            f'pgrep -af "{SIM_RUNTIME_PROCESS_PATTERN}" || true; '
            'echo "--- devices ---"; '
            + "ls -l "
            + " ".join(shlex.quote(dev) for dev in _diag_devices(hw))
            + " 2>/dev/null || true; "
            'echo "--- api ---"; '
            f"curl {CURL_OPTIONS} http://127.0.0.1:8080/api/state || true"
        )

    def build_component_status(self, hw_definition: dict[str, list[dict[str, str]]]) -> str:
        services = json.dumps(_runtime_services(hw_definition))
        script = f"""
services = {services}
result = {{}}
for service in services:
    result[service] = service_state(service)
result[SERVICE]['identity'] = observe_service(result[SERVICE])
print(json.dumps(result))
"""
        return remote_identity_command(script)

    def build_sim_log(self) -> str:
        return (
            'echo "--- journalctl gar runtime ---"; '
            "journalctl --no-pager -n 120 "
            "-u gar-sim.target -u gar-gpio-sim.service -u gar-bridge.service "
            "-u gar-v4l2-camera.service -u gar-sim-app.service "
            "-u 'gar-cuse-i2c@*.service' -u 'gar-cuse-spi@*.service' || true; "
            'echo "--- V4L2 ---"; '
            "if [ -e /dev/video0 ] && command -v v4l2-ctl >/dev/null; then "
            "v4l2-ctl --device=/dev/video0 --all --list-formats-ext 2>&1 || true; fi; "
            'echo "--- UDP sockets ---"; '
            "if command -v ss >/dev/null; then ss -uapn 2>&1 || true; fi; "
            'echo "--- legacy logs ---"; '
            "tail -n 80 /tmp/bridge.log /tmp/cuse.log /tmp/cuse_spi.log 2>/dev/null || true"
        )

    def build_gpio_runtime_status(self, hw_definition: dict[str, list[dict[str, str]]]) -> str:
        hw = hw_definition
        gpiochip_path = _gpiochip_path(hw)
        return (
            'echo "@@SERVICE@@"; '
            "systemctl is-active gar-gpio-sim.service 2>/dev/null || true; "
            'echo "@@DEVICE@@"; '
            f"if [ -e {shlex.quote(gpiochip_path)} ]; then echo {shlex.quote(gpiochip_path)} 1; "
            f"else echo {shlex.quote(gpiochip_path)} 0; fi; "
            'echo "@@MOUNT@@"; '
            f"if mountpoint -q {shlex.quote(gpiochip_path)}; then echo 1; "
            f"findmnt -n -o SOURCE --target {shlex.quote(gpiochip_path)} 2>/dev/null || true; "
            "else echo 0; fi; "
            'echo "@@CONFIGFS@@"; '
            "base=/sys/kernel/config/gpio-sim/gar; "
            'if [ -d "$base" ]; then echo 1; '
            'if [ -f "$base/live" ]; then cat "$base/live"; else echo "?"; fi; '
            'if [ -f "$base/bank0/chip_name" ]; then cat "$base/bank0/chip_name"; else echo ""; fi; '
            "else echo 0; fi; "
            'echo "@@GPIOCHIPS@@"; '
            "ls -1 /dev/gpiochip* 2>/dev/null || true"
        )

    def build_gpio_sim_check(self) -> str:
        return SIM_GPIO_SIM_CHECK_COMMAND

    def build_io(self, action: str, params: dict) -> str:
        device = str(params.get("device") or "") or None
        request = io_actions.resolve(action, device, params)
        url = f"{PANEL_BASE_URL}{request.path}"
        if request.fields:
            url += "?" + urlencode(request.fields, safe=":")
        if request.method == "GET":
            return f"curl {CURL_OPTIONS} {shlex.quote(url)}"
        return f"curl {CURL_OPTIONS} -X {request.method} {shlex.quote(url)}"
