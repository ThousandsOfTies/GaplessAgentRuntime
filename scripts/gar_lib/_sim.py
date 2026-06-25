"""`gar sim` subcommand: simulation runtime control over SSH."""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

from scripts.gar_lib._config import (
    default_ec2_host,
    load_config,
)
from scripts.gar_lib._hw import load_hw_definition
from scripts.gar_lib._vscode import write_vscode_terminal_profile
from scripts.gar_lib.environments.base import DevEnvironment
from scripts.gar_lib.environments.discovery import discover_environment_providers
from scripts.gar_lib.sim.base import SimProvider
from scripts.gar_lib.sim.linux import LinuxSimCommandBuilder, LinuxSystemdSimProvider
from scripts.gar_lib.sim.wokwi import WokwiSimProvider


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


def _get_sim_target(host: str) -> SimProvider:
    provider = _get_sim_provider()
    if provider.provider_id == "wokwi":
        return WokwiSimProvider(provider, host)
    return LinuxSystemdSimProvider(provider, host, LinuxSimCommandBuilder())


def run_sim_diag_json(host: str) -> int:
    """Run ``gar sim env diag --json``: print structured JSON, exit 0 when ok."""
    target = _get_sim_target(host)
    return target.diag_json(load_hw_definition())


def run_gpio_sim_check(host: str, *, json_output: bool = False) -> int:
    """Probe whether the remote simulation host can use the kernel gpio-sim."""
    target = _get_sim_target(host)
    return target.gpio_sim_check(json_output=json_output)


def run_sim_gpio_command(
    command: str,
    *,
    host: str | None = None,
    json_output: bool = False,
) -> int:
    resolved_host = host or default_ec2_host(load_config())
    target = _get_sim_target(resolved_host)
    return target.gpio_command(command, load_hw_definition(), json_output=json_output)


def run_sim_panel(
    action: str,
    *,
    host: str | None = None,
    json_output: bool = False,
    **params,
) -> int:
    """Drive the virtual panel / display over SSH by calling the bridge API."""
    resolved_host = host or default_ec2_host(load_config())
    target = _get_sim_target(resolved_host)
    return target.panel(action, params, json_output=json_output)


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
    resolved_host = host or default_ec2_host(load_config())
    target = _get_sim_target(resolved_host)
    hw_definition = load_hw_definition()

    if command == "status":
        if json_output:
            return target.status(hw_definition, json_output=True)
        port_forward_result = status_sim_port_forward(resolved_host)
        state_result = show_sim_state(resolved_host)
        return port_forward_result or state_result

    if command == "diag" and json_output:
        return target.diag_json(hw_definition)

    if command == "gpio-sim-check":
        return target.gpio_sim_check(json_output=json_output)

    if command == "start":
        result = target.start(hw_definition)
        if result != 0:
            return result
        write_sim_terminal_profile(
            host=resolved_host,
            settings=settings,
            profile_name=profile_name,
        )
        if port_forward:
            return start_sim_port_forward(resolved_host)
        return 0

    if command == "stop":
        result = target.stop(hw_definition)
        if result != 0:
            return result
        if stop_port_forward:
            return stop_sim_port_forward(resolved_host)
        return 0

    if command == "diag":
        return target.status(hw_definition, json_output=False)

    if command == "log":
        return target.log()

    print(f"unknown sim command: {command}", file=sys.stderr)
    return 1


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
    target = _get_sim_target(host)
    # We can reuse the panel command to get state via curl directly.
    # Wait, the panel command "state" prints it. The previous code did:
    # provider.run_remote(host, "curl -s http://127.0.0.1:8080/api/state")
    # Our target.panel("state") prints it if we pass json_output=False (the default).
    # However, in target.panel, the "state" command parses and prints pretty JSON.
    # The original show_sim_state just does `curl -s http...` and prints raw.
    # Let's use target.panel("state", params={}, json_output=True) to just dump it,
    # but since target.panel handles printing, we can just call it.
    return target.panel("state", params={}, json_output=True)


def write_sim_terminal_profile(
    *,
    host: str,
    settings: str | None = None,
    profile_name: str | None = None,
) -> None:
    home = Path.home()
    provider = _get_sim_provider()
    settings_path = Path(
        settings
        or os.environ.get(
            "GAR_SIM_SETTINGS",
            str(home / ".vscode-server" / "data" / "Machine" / "settings.json"),
        )
    ).expanduser()
    default_profile_name = "Wokwi Simulation" if provider.provider_id == "wokwi" else "EC2 Simulation"
    selected_profile_name = profile_name or os.environ.get(
        "GAR_SIM_PROFILE_NAME",
        default_profile_name,
    )
    terminal_bin = home / ".local" / "bin" / "gar-sim-terminal"
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
