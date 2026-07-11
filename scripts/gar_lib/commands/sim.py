"""`gar sim` subcommand: simulation runtime control over SSH."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

from scripts.gar_lib.artifacts.manifest import (
    default_artifacts_dir,
    get_provider,
    load_deploy_files,
    resolve_artifact_src,
)
from scripts.gar_lib.commands.hw import load_hw_definition
from scripts.gar_lib.config import (
    default_ec2_host,
    load_config,
    set_active_workspace_root,
)
from scripts.gar_lib.environments.base import DevEnvironment
from scripts.gar_lib.environments.discovery import discover_environment_providers
from scripts.gar_lib.simulation.base import SimEnvProcessor
from scripts.gar_lib.simulation.linux import LinuxSimCommandBuilder, LinuxSystemdSimEnvProcessor
from scripts.gar_lib.simulation.mujoco import MujocoSimEnvProcessor
from scripts.gar_lib.simulation.wokwi import WokwiSimEnvProcessor
from scripts.gar_lib.vscode.profile_manage import write_vscode_terminal_profile

SIM_DEST_MAP = {
    "~/cuse_i2c": "/usr/local/sbin/cuse_i2c",
    "~/cuse_spi": "/usr/local/sbin/cuse_spi",
    "~/web-bridge": "/usr/local/lib/gar/web-bridge",
}
SIM_DEST_PREFIX_MAP = {
    "~/web-bridge/": "/usr/local/lib/gar/web-bridge/",
}


def _get_sim_provider(provider_override: str | None = None) -> type[DevEnvironment]:
    config = load_config()
    pid = provider_override or os.environ.get("GAR_SIM_PROVIDER") or config.get("selected_providers", {}).get("simulator")
    providers = discover_environment_providers()
    if pid:
        for p in providers:
            if p.provider_id == pid:
                return p
    for p in providers:
        if p.provider_id == "ssh_remote":
            return p
    raise RuntimeError("No simulation provider found")


def run_sim_deploy_command(artifacts_dir: str | None, *, host: str | None, section: str = "app") -> int:
    """``gar sim deploy`` / ``gar sim env deploy``: resolve the artifact bundle
    root and push its ``deploy.<section>`` files to the simulation host.
    """
    root = Path(artifacts_dir).expanduser().resolve() if artifacts_dir else default_artifacts_dir().resolve()
    return deploy_sim_artifacts(root, host=host, section=section)


def deploy_sim_artifacts(root: Path, *, host: str | None, section: str = "app") -> int:
    resolved_host = host or default_ec2_host(load_config())
    loaded = load_deploy_files(root, section)
    if loaded is None:
        return 1

    bundle_root, files = loaded
    provider = get_provider("simulator")

    for entry in files:
        source = resolve_artifact_src(bundle_root, entry["src"])
        if source is None:
            return 1

        target_dest = sim_dest_path(entry["dest"])
        staging_path = f"/tmp/gar-deploy-{os.getpid()}-{source.name}"

        result = provider.push_file(resolved_host, source, staging_path)
        if result != 0:
            return result

        mode = entry.get("mode")
        install_command = remote_install_command(
            staging_path,
            target_dest,
            source_is_dir=source.is_dir(),
            mode=mode if isinstance(mode, str) else None,
        )
        proc = provider.run_remote(resolved_host, install_command, check=False)
        if proc.returncode != 0:
            return proc.returncode

    return 0


def sim_dest_path(manifest_dest: str) -> str:
    mapped = SIM_DEST_MAP.get(manifest_dest)
    if mapped:
        return mapped
    for source_prefix, target_prefix in SIM_DEST_PREFIX_MAP.items():
        if manifest_dest.startswith(source_prefix):
            return target_prefix + manifest_dest.removeprefix(source_prefix)
    return manifest_dest


def _shlex_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _remote_path_expr(dest: str) -> str:
    if dest == "~":
        return '"${HOME}"'
    if dest.startswith("~/"):
        return f'"${{HOME}}"/{_shlex_quote(dest[2:])}'
    return _shlex_quote(dest)


def remote_install_command(staging_path: str, dest: str, *, source_is_dir: bool, mode: str | None) -> str:
    dest_expr = _remote_path_expr(dest)
    if dest.startswith("~"):
        commands = [f"mkdir -p $(dirname {dest_expr})"]
        if source_is_dir:
            commands.append(f"mkdir -p {dest_expr}")
            commands.append(f"cp -a {_shlex_quote(staging_path)}/. {dest_expr}/")
        else:
            commands.append(f"cp {_shlex_quote(staging_path)} {dest_expr}")
        if mode:
            commands.append(f"chmod {_shlex_quote(mode)} {dest_expr}")
        return "; ".join(commands)

    commands = [f"sudo mkdir -p $(dirname {dest_expr})"]
    if source_is_dir:
        commands.append(f"sudo mkdir -p {dest_expr}")
        commands.append(f"sudo cp -a {_shlex_quote(staging_path)}/. {dest_expr}/")
    else:
        commands.append(f"sudo cp {_shlex_quote(staging_path)} {dest_expr}")
    if mode:
        commands.append(f"sudo chmod {_shlex_quote(mode)} {dest_expr}")
    return "; ".join(commands)


def _get_sim_target(host: str | None, *, provider_override: str | None = None) -> SimEnvProcessor:
    provider = _get_sim_provider(provider_override)
    if provider.provider_id == "wokwi":
        return WokwiSimEnvProcessor(provider, host)
    if provider.provider_id == "mujoco":
        return MujocoSimEnvProcessor(provider, host)
    return LinuxSystemdSimEnvProcessor(provider, host, LinuxSimCommandBuilder())


def run_sim_env_build_command(
    *,
    provider: str | None = None,
    workspace_root: str | None = None,
    json_output: bool = False,
) -> int:
    """``gar sim env build``: resolve the simulation provider and call its
    ``build()``. ``provider`` lets a caller narrow the resolution beyond the
    ``gar setup`` saved config (``selected_providers.simulation``).
    """
    resolved_provider = _get_sim_provider(provider)
    if resolved_provider.provider_id == "wokwi":
        if workspace_root is None:
            return run_product_sim_build()
        return run_product_sim_build(workspace_root=workspace_root)
    if resolved_provider.provider_id == "mujoco":
        target = _get_sim_target(host=None, provider_override="mujoco")
        return target.build(json_output=json_output)
    target = _get_sim_target(host=None, provider_override=resolved_provider.provider_id)
    try:
        return target.build(json_output=json_output)
    except NotImplementedError:
        print(
            "gar sim env build: 現在の設定では対応する build が見つかりません。\n"
            f"  simulation: {resolved_provider.provider_id}\n"
            "  --provider で明示的に指定するか、`gar setup` で Wokwi を選択してください。",
            file=sys.stderr,
        )
        return 1


def run_product_sim_build(*, workspace_root: str | None = None, clean: bool = False) -> int:
    """Run the selected product's simulation build hook or clean its output."""
    if workspace_root is not None:
        # A selector may be either a local path, a GAR-generated workspace ID,
        # or the user-facing workspace name shown by `gar setup`.
        set_active_workspace_root(workspace_root)
    config = load_config()
    development = config.get("selected_providers", {}).get("codespace")
    connection = config.get("workspace_connection")
    if not isinstance(connection, dict):
        print("gar sim build: product workspace が未設定です。`gar setup` を実行してください。", file=sys.stderr)
        return 1
    if development == "local":
        if connection.get("type") != "local":
            print("gar sim build: local provider には local workspace を選択してください。", file=sys.stderr)
            return 1
        script = Path(connection["path"]) / "scripts" / "product-sim-build.sh"
        if not script.is_file():
            print(f"gar sim build: product build hook が見つかりません: {script}", file=sys.stderr)
            return 1
        command = [str(script)]
        if clean:
            command.append("clean")
        return subprocess.run(command, check=False).returncode

    if development == "github_codespaces":
        if connection.get("type") != "codespaces":
            print("gar sim build: Codespaces provider には Codespaces workspace を選択してください。", file=sys.stderr)
            return 1
        codespace = connection.get("codespace")
        workspace_root = connection.get("path")
        if not isinstance(codespace, str) or not isinstance(workspace_root, str):
            print("gar sim build: Codespaces workspace 設定が不完全です。`gar setup` を実行してください。", file=sys.stderr)
            return 1
        hook_args = " clean" if clean else ""
        command = f"cd {shlex.quote(workspace_root)} && scripts/product-sim-build.sh{hook_args}"
        return subprocess.run(["gh", "codespace", "ssh", "-c", codespace, "--", command], check=False).returncode

    if connection.get("type") == "network":
        print("gar sim build: network workspace は build 実行先にできません。Codespaces workspace を選択してください。", file=sys.stderr)
        return 1

    print("gar sim build: development provider が未設定です。`gar setup` を実行してください。", file=sys.stderr)
    return 1


def run_sim_host_command(
    command: str,
    *,
    host: str | None = None,
    instance_id: str | None = None,
    region: str | None = None,
    update_ssh: bool = True,
    pull: bool = False,
    json_output: bool = False,
) -> int:
    """``gar sim start/stop/status``: resolve the simulation provider and call
    its ``host_command()``.
    """
    provider = _get_sim_provider()
    try:
        return provider.host_command(
            command,
            host=host,
            instance_id=instance_id,
            region=region,
            update_ssh=update_ssh,
            pull=pull,
            json_output=json_output,
        )
    except NotImplementedError:
        print(
            f"gar sim {command}: 現在の設定では対応するホストVM操作が見つかりません。\n"
            f"  simulation: {provider.provider_id}\n"
            "  `gar setup` で SSH Remote を選択してください。",
            file=sys.stderr,
        )
        return 1


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
