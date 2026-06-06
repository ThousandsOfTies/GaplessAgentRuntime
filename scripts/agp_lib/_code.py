"""`agp code` subcommand: Codespace SSHFS mount and VSCode terminal profile."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.agp_lib._vscode import (
    remove_vscode_terminal_profile,
    write_vscode_terminal_profile,
)
from scripts.agp_lib.environments.base import DevEnvironment
from scripts.agp_lib.environments.discovery import discover_environment_providers


def _get_dev_provider() -> type[DevEnvironment]:
    from scripts.agp_lib._config import load_config
    config = load_config()
    pid = config.get("selected_providers", {}).get("development")
    providers = discover_environment_providers()
    if pid:
        for p in providers:
            if p.provider_id == pid:
                return p
    for p in providers:
        if p.provider_id == "github_codespaces":
            return p
    raise RuntimeError("No development provider found")

DEFAULT_GH_TIMEOUT_SECONDS = 60


def run_code_command(
    command: str,
    *,
    codespace: str | None = None,
    remote_path: str | None = None,
    mount_dir: str | None = None,
    settings: str | None = None,
    profile_name: str | None = None,
    no_mount: bool = False,
    gh_timeout: int | None = None,
) -> int:
    if command == "start":
        return start_code_codespace(
            codespace=codespace,
            remote_path=remote_path,
            mount_dir=mount_dir,
            settings=settings,
            profile_name=profile_name,
            no_mount=no_mount,
            gh_timeout=gh_timeout,
        )
    if command == "stop":
        return stop_code_codespace(
            mount_dir=mount_dir,
            settings=settings,
            profile_name=profile_name,
        )

    print(f"unknown code command: {command}", file=sys.stderr)
    return 1


def start_code_codespace(
    *,
    codespace: str | None = None,
    remote_path: str | None = None,
    mount_dir: str | None = None,
    settings: str | None = None,
    profile_name: str | None = None,
    no_mount: bool = False,
    gh_timeout: int | None = None,
) -> int:
    home = Path.home()
    selected_codespace = codespace or os.environ.get("CODESPACE_NAME")
    selected_remote_path = remote_path or os.environ.get(
        "CODESPACE_REMOTE_PATH",
        "/workspaces/AgentCockpit",
    )
    selected_mount_dir = Path(
        mount_dir if mount_dir is not None else default_codespaces_mount_dir()
    ).expanduser()
    settings_path = Path(
        settings
        or os.environ.get(
            "CODESPACE_SETTINGS",
            str(home / ".vscode-server" / "data" / "Machine" / "settings.json"),
        )
    ).expanduser()
    selected_profile_name = profile_name or os.environ.get(
        "CODESPACE_PROFILE_NAME",
        "Codespaces",
    )
    selected_gh_timeout = gh_timeout_seconds(gh_timeout)
    state_dir = home / ".config" / "codespace-dev"
    state_file = state_dir / "env"
    terminal_bin = home / ".local" / "bin" / "codespace-terminal"

    required = ["gh", "ssh"]
    if not no_mount:
        required.extend(["sshfs", "findmnt", "mountpoint"])
        if shutil.which("fusermount3") is None and shutil.which("fusermount") is None:
            print(
                "agp code start: missing required command: fusermount3 or fusermount",
                file=sys.stderr,
            )
            return 1

    for command_name in required:
        if shutil.which(command_name) is None:
            print(f"agp code start: missing required command: {command_name}", file=sys.stderr)
            return 1

    if not selected_codespace:
        list_result = run_gh_captured(
            ["gh", "codespace", "list"],
            timeout=selected_gh_timeout,
            label="list Codespaces",
        )
        if list_result is None:
            return 1
        if list_result.returncode != 0:
            print_completed_stderr(list_result)
            return list_result.returncode
        selected_codespace = select_codespace_from_list(list_result.stdout)

    if not selected_codespace:
        print("agp code start: no available Codespace found", file=sys.stderr)
        print("Pass one explicitly: agp code start --codespace NAME", file=sys.stderr)
        return 1

    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    terminal_bin.parent.mkdir(parents=True, exist_ok=True)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    ssh_dir.chmod(0o700)

    print(f"Fetching SSH config for Codespace: {selected_codespace}")
    config_result = run_gh_captured(
        ["gh", "codespace", "ssh", "-c", selected_codespace, "--config"],
        timeout=selected_gh_timeout,
        label=f"generate SSH config for Codespace {selected_codespace}",
    )
    if config_result is None:
        return 1
    if config_result.returncode != 0:
        print_completed_stderr(config_result)
        return config_result.returncode

    codespaces_config = ssh_dir / "codespaces"
    codespaces_config.write_text(config_result.stdout, encoding="utf-8")
    codespaces_config.chmod(0o600)

    ssh_config = ssh_dir / "config"
    current_ssh_config = ssh_config.read_text(encoding="utf-8") if ssh_config.exists() else ""
    if "Include ~/.ssh/codespaces" not in current_ssh_config:
        with ssh_config.open("a", encoding="utf-8") as f:
            f.write("\nMatch all\nInclude ~/.ssh/codespaces\n")
        ssh_config.chmod(0o600)

    host = first_ssh_host(config_result.stdout)
    if not host:
        print("agp code start: could not find Host in ~/.ssh/codespaces", file=sys.stderr)
        return 1

    if not remote_path_exists(host, selected_remote_path):
        detected_path = detect_codespace_workspace(host)
        if detected_path:
            selected_remote_path = detected_path

    state_file.write_text(
        "\n".join(
            [
                f"CODESPACE_NAME='{selected_codespace}'",
                f"CODESPACE_SSH_HOST='{host}'",
                f"CODESPACE_REMOTE_PATH='{selected_remote_path}'",
                f"CODESPACE_MOUNT_DIR='{selected_mount_dir}'",
                "",
            ]
        ),
        encoding="utf-8",
    )
    state_file.chmod(0o600)

    terminal_bin.write_text(codespace_terminal_script(), encoding="utf-8")
    terminal_bin.chmod(0o755)

    if not no_mount:
        result = mount_codespace_code(
            host=host,
            remote_path=selected_remote_path,
            mount_dir=selected_mount_dir,
        )
        if result != 0:
            return result

    write_vscode_terminal_profile(settings_path, selected_profile_name, terminal_bin)

    print(f"Codespace: {selected_codespace}")
    print(f"SSH host:  {host}")
    print(f"Remote:    {selected_remote_path}")
    print(f"Mount:     {selected_mount_dir}")
    print(f"State:     {state_file}")
    print(f"Terminal:  {terminal_bin}")
    print(f"Profile:   {selected_profile_name}")
    return 0


def stop_code_codespace(
    *,
    mount_dir: str | None = None,
    settings: str | None = None,
    profile_name: str | None = None,
) -> int:
    home = Path.home()
    state_file = home / ".config" / "codespace-dev" / "env"
    state = load_codespace_state(state_file)

    selected_mount_dir = Path(
        mount_dir
        or os.environ.get("CODESPACE_MOUNT_DIR")
        or state.get("CODESPACE_MOUNT_DIR")
        or str(default_codespaces_mount_dir())
    ).expanduser()
    settings_path = Path(
        settings
        or os.environ.get(
            "CODESPACE_SETTINGS",
            str(home / ".vscode-server" / "data" / "Machine" / "settings.json"),
        )
    ).expanduser()
    selected_profile_name = profile_name or os.environ.get(
        "CODESPACE_PROFILE_NAME",
        "Codespaces",
    )

    expected_source = None
    if state.get("CODESPACE_SSH_HOST") and state.get("CODESPACE_REMOTE_PATH"):
        expected_source = f"{state['CODESPACE_SSH_HOST']}:{state['CODESPACE_REMOTE_PATH']}"

    unmount_result = unmount_codespace_code(
        mount_dir=selected_mount_dir,
        expected_source=expected_source,
    )
    profile_result = remove_vscode_terminal_profile(settings_path, selected_profile_name)

    if state_file.exists():
        print(f"State:     kept {state_file}")
    print("SSH config: kept ~/.ssh/codespaces and Include entry")

    return unmount_result or profile_result


def load_codespace_state(state_file: Path) -> dict[str, str]:
    if not state_file.exists():
        return {}

    state: dict[str, str] = {}
    for raw_line in state_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        try:
            parsed = shlex.split(value, comments=False, posix=True)
        except ValueError:
            continue
        if key and parsed:
            state[key] = parsed[0]
    return state


def select_codespace_from_list(output: str) -> str | None:
    rows = codespace_list_rows(output)
    if len(rows) == 1:
        return rows[0][0]

    for fields in rows:
        if len(fields) >= 5 and fields[4] == "Available" and fields[0]:
            return fields[0]
    return None


def codespace_list_rows(output: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in output.splitlines():
        fields = line.split("\t")
        if not fields or not fields[0] or fields[0] == "NAME":
            continue
        rows.append(fields)
    return rows


def default_codespaces_mount_dir() -> Path:
    return Path.cwd() / "codespaces"


def gh_timeout_seconds(value: int | None) -> int | None:
    raw_value = str(value) if value is not None else os.environ.get("CODESPACE_GH_TIMEOUT", "")
    if not raw_value:
        return DEFAULT_GH_TIMEOUT_SECONDS
    try:
        timeout = int(raw_value)
    except ValueError:
        print(
            f"agp code start: invalid CODESPACE_GH_TIMEOUT={raw_value!r}; "
            f"using {DEFAULT_GH_TIMEOUT_SECONDS}s",
            file=sys.stderr,
        )
        return DEFAULT_GH_TIMEOUT_SECONDS
    return timeout if timeout > 0 else None


def run_gh_captured(
    argv: list[str],
    *,
    timeout: int | None,
    label: str,
) -> subprocess.CompletedProcess[str] | None:
    env = os.environ.copy()
    env.setdefault("GH_PROMPT_DISABLED", "1")
    try:
        return subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        timeout_text = "without a timeout" if timeout is None else f"after {timeout}s"
        print(
            f"agp code start: timed out {timeout_text} while trying to {label}",
            file=sys.stderr,
        )
        print("Check `gh auth status` and try `gh codespace list` directly.", file=sys.stderr)
        return None


def print_completed_stderr(result: subprocess.CompletedProcess[str]) -> None:
    message = (result.stderr or "").strip()
    if message:
        print(message, file=sys.stderr)


def first_ssh_host(config_text: str) -> str | None:
    for line in config_text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0] == "Host":
            return parts[1]
    return None


def remote_path_exists(host: str, remote_path: str) -> bool:
    provider = _get_dev_provider()
    result = provider.run_remote(host, f"test -d {shlex.quote(remote_path)}", capture_output=True, check=False)
    return result.returncode == 0


def detect_codespace_workspace(host: str) -> str | None:
    provider = _get_dev_provider()
    result = provider.run_remote(
        host,
        'find /workspaces -mindepth 1 -maxdepth 1 -type d ! -name ".*" 2>/dev/null | sort | head -n 1',
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    detected = result.stdout.strip()
    return detected or None


def mount_codespace_code(*, host: str, remote_path: str, mount_dir: Path) -> int:
    mount_dir.mkdir(parents=True, exist_ok=True)
    expected_source = f"{host}:{remote_path}"
    mountpoint_result = subprocess.run(["mountpoint", "-q", str(mount_dir)], check=False)

    if mountpoint_result.returncode == 0:
        source_result = subprocess.run(
            ["findmnt", "-n", "-o", "SOURCE", "--target", str(mount_dir)],
            check=False,
            capture_output=True,
            text=True,
        )
        current_source = source_result.stdout.strip() if source_result.returncode == 0 else ""
        if current_source == expected_source:
            print(f"sshfs: already mounted at {mount_dir}")
            return 0

        print(f"sshfs: replacing stale mount {current_source} at {mount_dir}")
        fusermount = shutil.which("fusermount3") or shutil.which("fusermount")
        if fusermount is None:
            print(
                "agp code start: missing required command: fusermount3 or fusermount",
                file=sys.stderr,
            )
            return 1
        unmount_result = subprocess.run([fusermount, "-u", str(mount_dir)], check=False)
        if unmount_result.returncode != 0:
            return unmount_result.returncode

    result = subprocess.run(
        [
            "sshfs",
            expected_source,
            str(mount_dir),
            "-o",
            "reconnect",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=3",
        ],
        check=False,
    )
    if result.returncode == 0:
        print(f"sshfs: mounted {expected_source} -> {mount_dir}")
    return result.returncode


def unmount_codespace_code(*, mount_dir: Path, expected_source: str | None) -> int:
    if not mount_dir.exists():
        print(f"sshfs: not mounted at {mount_dir}")
        return 0

    if shutil.which("mountpoint") is None:
        print("agp code stop: missing required command: mountpoint", file=sys.stderr)
        return 1

    mountpoint_result = subprocess.run(["mountpoint", "-q", str(mount_dir)], check=False)
    if mountpoint_result.returncode != 0:
        print(f"sshfs: not mounted at {mount_dir}")
        return 0

    if shutil.which("findmnt") is None:
        print("agp code stop: missing required command: findmnt", file=sys.stderr)
        return 1

    source_result = subprocess.run(
        ["findmnt", "-n", "-o", "SOURCE", "--target", str(mount_dir)],
        check=False,
        capture_output=True,
        text=True,
    )
    current_source = source_result.stdout.strip() if source_result.returncode == 0 else ""
    if expected_source is None:
        print(
            f"agp code stop: missing Codespace state; leaving mount untouched: {mount_dir}",
            file=sys.stderr,
        )
        return 1
    if current_source != expected_source:
        print(
            f"agp code stop: leaving non-matching mount untouched: {current_source} at {mount_dir}",
            file=sys.stderr,
        )
        return 1

    fusermount = shutil.which("fusermount3") or shutil.which("fusermount")
    if fusermount is None:
        print("agp code stop: missing required command: fusermount3 or fusermount", file=sys.stderr)
        return 1

    result = subprocess.run([fusermount, "-u", str(mount_dir)], check=False)
    if result.returncode == 0:
        print(f"sshfs: unmounted {mount_dir}")
    return result.returncode


def codespace_terminal_script() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

state_file="${CODESPACE_DEV_ENV:-$HOME/.config/codespace-dev/env}"

if [[ ! -f "$state_file" ]]; then
  echo "codespace-terminal: missing $state_file" >&2
  echo "Run: agp code start" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$state_file"

if [[ -z "${CODESPACE_SSH_HOST:-}" ]]; then
  echo "codespace-terminal: CODESPACE_SSH_HOST is not set in $state_file" >&2
  exit 1
fi

if [[ -n "${CODESPACE_REMOTE_PATH:-}" ]]; then
  exec ssh -t "$CODESPACE_SSH_HOST" "cd '$CODESPACE_REMOTE_PATH' && exec bash -l"
fi

exec ssh -t "$CODESPACE_SSH_HOST"
"""
