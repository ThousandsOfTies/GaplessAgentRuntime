"""`agp sim` bash script generation."""
from __future__ import annotations
import json
import shlex
import textwrap

def build_gpio_systemd_install_command(hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
    from scripts.agp_lib._hw import load_hw_definition
    from scripts.agp_lib._sim import (
        AGP_RUN_DIR, AGP_HW_SIM_SOCK, AGP_HARDWARE_DIR,
        AGP_GPIO_SIM_START, AGP_GPIO_SIM_STOP, AGP_ETC_DIR, AGP_SBIN_DIR,
        _hardware_csv_install_commands, _sudo_write_file_command
    )
    hw = hw_definition or load_hw_definition()
    gpio_start_script = "#!/bin/sh\n" + build_gpio_sim_setup_command(hw) + "\n"
    gpio_stop_script = "#!/bin/sh\n" + build_gpio_sim_teardown_command(hw) + "\n"
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

def build_sim_diag_json_command(hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
    from scripts.agp_lib._hw import load_hw_definition
    from scripts.agp_lib._sim import _diag_devices, SIM_DIAG_DEVICES
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

def build_gpio_sim_setup_command(hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
    from pathlib import Path
    from scripts.agp_lib._hw import load_hw_definition
    from scripts.agp_lib._sim import _gpio_rows, _gpiochip_path, _gpio_label
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
                "-exec chmod 666 {} \\; 2>/dev/null || true"
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

def build_gpio_sim_teardown_command(hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
    from scripts.agp_lib._hw import load_hw_definition
    from scripts.agp_lib._sim import _gpiochip_path
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

def build_systemd_install_command(hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
    from scripts.agp_lib._hw import load_hw_definition
    from scripts.agp_lib._sim import (
        AGP_RUN_DIR, AGP_HW_SIM_SOCK, AGP_HARDWARE_DIR, AGP_LIB_DIR,
        AGP_BRIDGE_DIR, AGP_BRIDGE_START, AGP_ETC_DIR, AGP_SBIN_DIR,
        AGP_GPIO_SIM_START, AGP_GPIO_SIM_STOP,
        AGP_CUSE_I2C, AGP_CUSE_SPI,
        _runtime_services, _sudo_write_file_command, _hardware_csv_install_commands
    )
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
        _sudo_write_file_command(AGP_GPIO_SIM_START, "#!/bin/sh\n" + build_gpio_sim_setup_command(hw) + "\n", mode="0755"),
        _sudo_write_file_command(AGP_GPIO_SIM_STOP, "#!/bin/sh\n" + build_gpio_sim_teardown_command(hw) + "\n", mode="0755"),
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

def build_systemd_start_command(hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
    from scripts.agp_lib._hw import load_hw_definition
    from scripts.agp_lib._sim import _runtime_services
    hw = hw_definition or load_hw_definition()
    services = " ".join(shlex.quote(service) for service in _runtime_services(hw))
    return (
        build_systemd_install_command(hw)
        + "; "
        + f"sudo systemctl stop agp-sim.target {services} >/dev/null 2>&1 || true; "
        + "sudo pkill -x cuse_i2c || true; "
        + "sudo pkill -x cuse_spi || true; "
        + "sudo systemctl start agp-sim.target; "
        + "sleep 3; "
        + "sudo systemctl --no-pager --full status agp-sim.target; "
        + 'pgrep -af "bridge.py|cuse_i2c|cuse_spi"'
    )

def build_systemd_stop_command(hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
    from scripts.agp_lib._hw import load_hw_definition
    from scripts.agp_lib._sim import _runtime_services
    hw = hw_definition or load_hw_definition()
    services = " ".join(shlex.quote(service) for service in reversed(_runtime_services(hw)))
    return (
        f"sudo systemctl stop agp-sim.target {services} >/dev/null 2>&1 || true; "
        "sudo pkill -x cuse_i2c || true; "
        "sudo pkill -x cuse_spi || true; "
        "pkill -f '[/]web-bridge/bridge.py' || true; "
        'echo "Simulation device runtime stopped."'
    )

def build_sim_start_command(hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
    return build_systemd_start_command(hw_definition)

def build_sim_stop_command(hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
    return build_systemd_stop_command(hw_definition)

def build_sim_status_command(hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
    from scripts.agp_lib._hw import load_hw_definition
    from scripts.agp_lib._sim import _diag_devices
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

def build_sim_log_command() -> str:
    return (
        'echo "--- journalctl agp runtime ---"; '
        "journalctl --no-pager -n 120 "
        "-u agp-sim.target -u agp-gpio-sim.service -u agp-bridge.service "
        "-u 'agp-cuse-i2c@*.service' -u 'agp-cuse-spi@*.service' || true; "
        'echo "--- legacy logs ---"; '
        "tail -n 80 /tmp/bridge.log /tmp/cuse.log /tmp/cuse_spi.log 2>/dev/null || true"
    )

def build_gpio_runtime_status_command(hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
    from scripts.agp_lib._hw import load_hw_definition
    from scripts.agp_lib._sim import _gpiochip_path
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

def build_panel_command(action: str, params: dict) -> str:
    """Build the remote ``curl`` command for a virtual panel action.

    Pure/string-only so it can be unit-tested without SSH. Mirrors the bridge
    HTTP API served on the simulation host's ``127.0.0.1:8080``.
    """
    from urllib.parse import quote
    from scripts.agp_lib._sim import PANEL_BASE_URL
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
