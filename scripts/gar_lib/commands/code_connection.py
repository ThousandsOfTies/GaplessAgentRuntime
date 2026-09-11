"""External command and SSHFS operations for ``gar code``."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.gar_lib.access.display import run_displayed

DEFAULT_GH_TIMEOUT_SECONDS = 60
SSH_CONFIG_INCLUDE = "Include ~/.ssh/codespaces"


def gh_timeout_seconds(
    value: int | None,
    *,
    command_name: str = "gar code start",
) -> int | None:
    """Resolve the GitHub CLI timeout from an argument or the environment."""

    raw_value = str(value) if value is not None else os.environ.get("CODESPACE_GH_TIMEOUT", "")
    if not raw_value:
        return DEFAULT_GH_TIMEOUT_SECONDS
    try:
        timeout = int(raw_value)
    except ValueError:
        message = f"{command_name}: invalid CODESPACE_GH_TIMEOUT={raw_value!r}; " f"using {DEFAULT_GH_TIMEOUT_SECONDS}s"
        print(
            message,
            file=sys.stderr,
        )
        return DEFAULT_GH_TIMEOUT_SECONDS
    return timeout if timeout > 0 else None


def run_gh_captured(
    argv: list[str],
    *,
    timeout: int | None,
    label: str,
    command_name: str = "gar code start",
) -> subprocess.CompletedProcess[str] | None:
    """Run a non-interactive ``gh`` command and explain a timeout to the user."""

    environment = os.environ.copy()
    environment.setdefault("GH_PROMPT_DISABLED", "1")
    try:
        return subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
        )
    except subprocess.TimeoutExpired:
        timeout_text = "without a timeout" if timeout is None else f"after {timeout}s"
        print(
            f"{command_name}: timed out {timeout_text} while trying to {label}",
            file=sys.stderr,
        )
        print("Check `gh auth status` and try `gh codespace list` directly.", file=sys.stderr)
        return None


def print_completed_stderr(result: subprocess.CompletedProcess[str]) -> None:
    message = (result.stderr or "").strip()
    if message:
        print(message, file=sys.stderr)


def install_codespace_ssh_config(home: Path, config_text: str) -> str | None:
    """Install generated SSH configuration and return its concrete host alias."""

    host = first_ssh_host(config_text)
    if host is None:
        return None

    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    ssh_dir.chmod(0o700)
    _write_private_text(ssh_dir / "codespaces", config_text)
    _ensure_codespaces_include(ssh_dir / "config")
    return host


def first_ssh_host(config_text: str) -> str | None:
    """Return the first usable (non-pattern) host alias from SSH config."""

    for line in config_text.splitlines():
        parts = line.strip().split()
        if len(parts) < 2 or parts[0].lower() != "host":
            continue
        for host in parts[1:]:
            if _is_concrete_ssh_host(host):
                return host
    return None


def remote_path_exists(
    codespace: str,
    remote_path: str,
    *,
    timeout: int | None = None,
) -> bool:
    command = f"test -d {shlex.quote(remote_path)}"
    result = run_codespace_remote(
        codespace,
        command,
        capture_output=True,
        timeout=timeout,
    )
    return result.returncode == 0


def detect_codespace_workspace(
    codespace: str,
    *,
    timeout: int | None = None,
) -> str | None:
    command = 'find /workspaces -mindepth 1 -maxdepth 1 -type d ! -name ".*" 2>/dev/null | sort | head -n 1'
    result = run_codespace_remote(
        codespace,
        command,
        capture_output=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        return None
    detected = result.stdout.strip()
    return detected or None


def run_codespace_remote(
    codespace: str,
    command: str,
    *,
    capture_output: bool = False,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.setdefault("GH_PROMPT_DISABLED", "1")
    return run_displayed(
        ["gh", "codespace", "ssh", "-c", codespace, "--", command],
        runner=subprocess.run,
        check=False,
        capture_output=capture_output,
        text=True,
        timeout=timeout,
        env=environment,
    )


def mount_codespace_code(*, host: str, remote_path: str, mount_dir: Path) -> int:
    """Mount the requested remote directory, replacing only a known stale mount."""

    mount_dir.mkdir(parents=True, exist_ok=True)
    expected_source = f"{host}:{remote_path}"
    mountpoint_result = run_displayed(["mountpoint", "-q", str(mount_dir)], runner=subprocess.run, check=False)

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
        unmount_result = _run_fusermount(mount_dir, command_name="gar code start")
        if unmount_result != 0:
            return unmount_result

    result = run_displayed(
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
        runner=subprocess.run,
        check=False,
    )
    if result.returncode == 0:
        print(f"sshfs: mounted {expected_source} -> {mount_dir}")
    return result.returncode


def unmount_codespace_code(*, mount_dir: Path, expected_source: str | None) -> int:
    """Unmount only when state confirms that the mount belongs to ``gar code``."""

    if not mount_dir.exists():
        print(f"sshfs: not mounted at {mount_dir}")
        return 0

    if shutil.which("mountpoint") is None:
        print("gar code stop: missing required command: mountpoint", file=sys.stderr)
        return 1

    mountpoint_result = run_displayed(["mountpoint", "-q", str(mount_dir)], runner=subprocess.run, check=False)
    if mountpoint_result.returncode != 0:
        print(f"sshfs: not mounted at {mount_dir}")
        return 0

    if shutil.which("findmnt") is None:
        print("gar code stop: missing required command: findmnt", file=sys.stderr)
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
            f"gar code stop: missing Codespace state; leaving mount untouched: {mount_dir}",
            file=sys.stderr,
        )
        return 1
    if current_source != expected_source:
        print(
            f"gar code stop: leaving non-matching mount untouched: {current_source} at {mount_dir}",
            file=sys.stderr,
        )
        return 1

    result = _run_fusermount(mount_dir, command_name="gar code stop")
    if result == 0:
        print(f"sshfs: unmounted {mount_dir}")
    return result


def _ensure_codespaces_include(ssh_config: Path) -> None:
    try:
        current = ssh_config.read_text(encoding="utf-8")
    except FileNotFoundError:
        current = ""
    if any(line.strip() == SSH_CONFIG_INCLUDE for line in current.splitlines()):
        return

    separator = "" if not current or current.endswith("\n") else "\n"
    updated = f"{current}{separator}\nMatch all\n{SSH_CONFIG_INCLUDE}\n"
    _write_private_text(ssh_config, updated)


def _write_private_text(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{path.name}-",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    ) as output:
        temporary_path = Path(output.name)
        output.write(contents)
        output.flush()
        os.fsync(output.fileno())

    try:
        temporary_path.chmod(0o600)
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _is_concrete_ssh_host(host: str) -> bool:
    if not host or host.startswith("-"):
        return False
    if any(character in host for character in "*?!"):
        return False
    return "\0" not in host and "\n" not in host and "\r" not in host


def _run_fusermount(mount_dir: Path, *, command_name: str) -> int:
    fusermount = shutil.which("fusermount3") or shutil.which("fusermount")
    if fusermount is None:
        print(
            f"{command_name}: missing required command: fusermount3 or fusermount",
            file=sys.stderr,
        )
        return 1
    return run_displayed([fusermount, "-u", str(mount_dir)], runner=subprocess.run, check=False).returncode
