from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import shlex
import shutil
import subprocess
import sys
from collections.abc import Sequence
import os
from pathlib import Path
import uuid

from scripts.agp_lib.environments.base import DevEnvironment
from scripts.agp_lib.environments.discovery import discover_environment_providers


RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
BLUE = "\033[34m"
CONFIG_PATH = Path(".agp") / "config.json"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
VSCODE_EXT_NAME = "agentcockpit-terminal-bridge"
VSCODE_EXT_VERSION = "0.0.1"


def _use_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def style(text: str, *codes: str) -> str:
    if not _use_color() or not codes:
        return text
    return "".join(codes) + text + RESET


def safe_input(prompt: str, *, default_on_eof: str = "q") -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        print()
        print(style("入力を受け取れないため、対話処理を終了します。", YELLOW))
        return default_on_eof
    except KeyboardInterrupt:
        print()
        print(style("入力が中断されたため、対話処理を終了します。", YELLOW))
        return default_on_eof


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agp")
    subparsers = parser.add_subparsers(dest="command")

    setup_parser = subparsers.add_parser(
        "setup",
        help="接続環境プロバイダを選択して依存コマンドを確認します",
    )
    setup_parser.add_argument(
        "--no-install",
        action="store_true",
        help="不足コマンドのインストール処理を実行せず案内だけ表示します",
    )
    setup_parser.add_argument(
        "--ec2-host",
        default=None,
        help="agp sim が既定で使う SSH config 上の runtime host 名",
    )
    code_parser = subparsers.add_parser(
        "code",
        help="Build Artifacts workspace との接続を管理します",
    )
    code_subparsers = code_parser.add_subparsers(dest="code_command")
    code_start_parser = code_subparsers.add_parser(
        "start",
        help="Codespace build workspace を WSL hub から見えるようにします",
    )
    code_start_parser.add_argument(
        "--codespace",
        default=None,
        help="接続する Codespace 名",
    )
    code_start_parser.add_argument(
        "--remote-path",
        default=None,
        help="Codespace 側 workspace path",
    )
    code_start_parser.add_argument(
        "--mount-dir",
        default=None,
        help="WSL 側 sshfs mount path",
    )
    code_start_parser.add_argument(
        "--settings",
        default=None,
        help="VS Code settings.json path",
    )
    code_start_parser.add_argument(
        "--profile-name",
        default=None,
        help="VS Code terminal profile 名",
    )
    code_start_parser.add_argument(
        "--no-mount",
        action="store_true",
        help="sshfs mount を更新せず、SSH 設定と terminal profile だけ更新します",
    )
    code_stop_parser = code_subparsers.add_parser(
        "stop",
        help="Codespace build workspace の WSL hub 側接続を停止します",
    )
    code_stop_parser.add_argument(
        "--mount-dir",
        default=None,
        help="WSL 側 sshfs mount path",
    )
    code_stop_parser.add_argument(
        "--settings",
        default=None,
        help="VS Code settings.json path",
    )
    code_stop_parser.add_argument(
        "--profile-name",
        default=None,
        help="VS Code terminal profile 名",
    )
    terminal_parser = subparsers.add_parser(
        "terminal",
        help="VSCode integrated terminal への実行要求を作成します",
    )
    terminal_subparsers = terminal_parser.add_subparsers(dest="terminal_command")
    terminal_run_parser = terminal_subparsers.add_parser(
        "run",
        help="VSCode integrated terminal でコマンドを実行します",
    )
    terminal_run_parser.add_argument(
        "--title",
        default="AgentCockpit",
        help="VSCode terminal の表示名",
    )
    terminal_run_parser.add_argument(
        "--cwd",
        default=None,
        help="コマンドを実行する作業ディレクトリ",
    )
    terminal_run_parser.add_argument(
        "--command",
        dest="command_text",
        default=None,
        help="実行するコマンド文字列",
    )
    terminal_run_parser.add_argument(
        "command_parts",
        nargs=argparse.REMAINDER,
        help="実行するコマンド。例: agp terminal run -- agp setup",
    )
    sim_parser = subparsers.add_parser(
        "sim",
        help="simulation runtime を操作します",
    )
    sim_subparsers = sim_parser.add_subparsers(dest="sim_command")
    sim_deploy_parser = sim_subparsers.add_parser(
        "deploy",
        help="simulation runtime へ成果物を配置します",
    )
    sim_deploy_parser.add_argument(
        "--host",
        default=None,
        help="SSH config 上の runtime host 名。省略時は .agp/config.json の保存済み host",
    )
    sim_deploy_parser.add_argument(
        "--artifacts-dir",
        default=None,
        help="Codespace から WSL hub へコピー済みの成果物 root",
    )
    for command_name in ("start", "stop", "status", "diag", "log"):
        command_parser = sim_subparsers.add_parser(
            command_name,
            help=f"simulation runtime: {command_name}",
        )
        command_parser.add_argument(
            "--host",
            default=None,
            help="SSH config 上の runtime host 名。省略時は .agp/config.json の保存済み host",
        )
        if command_name == "start":
            command_parser.add_argument(
                "--settings",
                default=None,
                help="VS Code settings.json path",
            )
            command_parser.add_argument(
                "--profile-name",
                default=None,
                help="VS Code terminal profile 名",
            )
            command_parser.add_argument(
                "--no-port-forward",
                action="store_true",
                help="Hardware Panel 用の 8080/8765 port forward を開始しません",
            )
        if command_name == "stop":
            command_parser.add_argument(
                "--keep-port-forward",
                action="store_true",
                help="Hardware Panel 用の port forward を停止しません",
            )
    native_parser = subparsers.add_parser(
        "native",
        help="接続先の native I/O を使う runtime を操作します",
    )
    native_subparsers = native_parser.add_subparsers(dest="native_command")
    native_deploy_parser = native_subparsers.add_parser(
        "deploy",
        help="native runtime へ成果物を配置します",
    )
    native_deploy_parser.add_argument(
        "--serial",
        default=None,
        help="adb device serial。省略時は adb の既定接続先",
    )
    native_deploy_parser.add_argument(
        "--dest",
        default="/home/user",
        help="artifact.json の native dest が相対パスのときの接続先基準ディレクトリ",
    )
    native_deploy_parser.add_argument(
        "--artifacts-dir",
        default=None,
        help="Codespace から WSL hub へコピー済みの成果物 root",
    )

    args = parser.parse_args(argv)

    if args.command == "setup":
        return run_setup(no_install=args.no_install, ec2_host=args.ec2_host)
    if args.command == "code":
        if args.code_command is None:
            code_parser.print_help()
            return 1
        return run_code_command(
            args.code_command,
            codespace=getattr(args, "codespace", None),
            remote_path=getattr(args, "remote_path", None),
            mount_dir=getattr(args, "mount_dir", None),
            settings=getattr(args, "settings", None),
            profile_name=getattr(args, "profile_name", None),
            no_mount=getattr(args, "no_mount", False),
        )
    if args.command == "terminal" and args.terminal_command == "run":
        return run_terminal_request(
            command_parts=args.command_parts,
            command_text=args.command_text,
            title=args.title,
            cwd=args.cwd,
        )
    if args.command == "sim":
        if args.sim_command is None:
            sim_parser.print_help()
            return 1
        if args.sim_command == "deploy":
            return run_deploy_command(
                "sim",
                artifacts_dir=args.artifacts_dir,
                host=args.host,
            )
        return run_sim_command(
            args.sim_command,
            host=args.host,
            settings=getattr(args, "settings", None),
            profile_name=getattr(args, "profile_name", None),
            port_forward=not getattr(args, "no_port_forward", False),
            stop_port_forward=not getattr(args, "keep_port_forward", False),
        )
    if args.command == "native":
        if args.native_command is None:
            native_parser.print_help()
            return 1
        if args.native_command == "deploy":
            return run_deploy_command(
                "native",
                artifacts_dir=args.artifacts_dir,
                serial=args.serial,
                dest=args.dest,
            )

    parser.print_help()
    return 0


def run_code_command(
    command: str,
    *,
    codespace: str | None = None,
    remote_path: str | None = None,
    mount_dir: str | None = None,
    settings: str | None = None,
    profile_name: str | None = None,
    no_mount: bool = False,
) -> int:
    if command == "start":
        return start_code_codespace(
            codespace=codespace,
            remote_path=remote_path,
            mount_dir=mount_dir,
            settings=settings,
            profile_name=profile_name,
            no_mount=no_mount,
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
) -> int:
    home = Path.home()
    selected_codespace = codespace or os.environ.get("CODESPACE_NAME")
    selected_remote_path = remote_path or os.environ.get(
        "CODESPACE_REMOTE_PATH",
        "/workspaces/AgentCockpit",
    )
    selected_mount_dir = Path(
        mount_dir if mount_dir is not None else PROJECT_ROOT.parent / "codespaces"
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
        list_result = subprocess.run(
            ["gh", "codespace", "list"],
            check=False,
            capture_output=True,
            text=True,
        )
        if list_result.returncode != 0:
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

    config_result = subprocess.run(
        ["gh", "codespace", "ssh", "-c", selected_codespace, "--config"],
        check=False,
        capture_output=True,
        text=True,
    )
    if config_result.returncode != 0:
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
        or str(PROJECT_ROOT.parent / "codespaces")
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


def first_ssh_host(config_text: str) -> str | None:
    for line in config_text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0] == "Host":
            return parts[1]
    return None


def remote_path_exists(host: str, remote_path: str) -> bool:
    result = subprocess.run(
        ["ssh", "-T", host, f"test -d {shlex.quote(remote_path)}"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def detect_codespace_workspace(host: str) -> str | None:
    result = subprocess.run(
        [
            "ssh",
            "-T",
            host,
            'find /workspaces -mindepth 1 -maxdepth 1 -type d ! -name ".*" 2>/dev/null | sort | head -n 1',
        ],
        check=False,
        capture_output=True,
        text=True,
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


def write_vscode_terminal_profile(
    settings_path: Path,
    profile_name: str,
    terminal_bin: Path,
) -> None:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if settings_path.exists() and settings_path.stat().st_size:
        data = json.loads(settings_path.read_text(encoding="utf-8"))

    profiles = data.setdefault("terminal.integrated.profiles.linux", {})
    profiles[profile_name] = {"path": str(terminal_bin)}
    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def remove_vscode_terminal_profile(settings_path: Path, profile_name: str) -> int:
    if not settings_path.exists() or settings_path.stat().st_size == 0:
        print(f"Profile:   not present ({profile_name})")
        return 0

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"agp code stop: invalid VS Code settings JSON: {settings_path}", file=sys.stderr)
        return 1

    profiles = data.get("terminal.integrated.profiles.linux")
    if not isinstance(profiles, dict) or profile_name not in profiles:
        print(f"Profile:   not present ({profile_name})")
        return 0

    del profiles[profile_name]
    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Profile:   removed {profile_name} from {settings_path}")
    return 0


def run_deploy_command(
    target: str,
    *,
    artifacts_dir: str | None = None,
    host: str | None = None,
    serial: str | None = None,
    dest: str = "/home/user",
) -> int:
    root = Path(artifacts_dir).expanduser() if artifacts_dir else default_artifacts_dir()
    root = root.resolve()

    if target == "sim":
        return deploy_sim_artifacts(root, host=host)
    if target == "native":
        return deploy_native_artifacts(root, serial=serial, dest=dest)

    print(f"unknown deploy target: {target}", file=sys.stderr)
    return 1


def default_artifacts_dir() -> Path:
    return PROJECT_ROOT.parent / "agp-build-env" / "artifacts" / "from-codespace"


def find_artifact_manifest(root: Path) -> Path | None:
    direct = root / "artifact.json"
    if direct.exists():
        return direct

    candidates = sorted(path for path in root.iterdir() if (path / "artifact.json").exists()) if root.exists() else []
    if len(candidates) == 1:
        return candidates[0] / "artifact.json"
    return None


def load_artifact_manifest(root: Path) -> tuple[Path, dict] | None:
    manifest_path = find_artifact_manifest(root)
    if manifest_path is None:
        print(f"missing artifact manifest: {root / 'artifact.json'}", file=sys.stderr)
        return None

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"invalid artifact manifest JSON: {manifest_path}: {exc}", file=sys.stderr)
        return None

    if not isinstance(data, dict):
        print(f"invalid artifact manifest: root must be an object: {manifest_path}", file=sys.stderr)
        return None

    return manifest_path.parent, data


def artifact_deploy_files(manifest: dict, target: str) -> list[dict] | None:
    deploy = manifest.get("deploy")
    if not isinstance(deploy, dict):
        print("invalid artifact manifest: deploy must be an object", file=sys.stderr)
        return None

    target_config = deploy.get(target)
    if not isinstance(target_config, dict):
        print(f"artifact manifest has no deploy.{target} section", file=sys.stderr)
        return None

    files = target_config.get("files")
    if not isinstance(files, list) or not files:
        print(f"artifact manifest deploy.{target}.files must be a non-empty list", file=sys.stderr)
        return None

    for index, entry in enumerate(files):
        if not isinstance(entry, dict):
            print(f"artifact manifest deploy.{target}.files[{index}] must be an object", file=sys.stderr)
            return None
        if not isinstance(entry.get("src"), str) or not isinstance(entry.get("dest"), str):
            print(
                f"artifact manifest deploy.{target}.files[{index}] requires string src and dest",
                file=sys.stderr,
            )
            return None

    return files


def resolve_artifact_src(bundle_root: Path, src: str) -> Path | None:
    source = (bundle_root / src).resolve()
    try:
        source.relative_to(bundle_root)
    except ValueError:
        print(f"artifact src escapes bundle root: {src}", file=sys.stderr)
        return None

    if not source.exists():
        print(f"missing artifact: {source}", file=sys.stderr)
        return None

    return source


def load_deploy_files(root: Path, target: str) -> tuple[Path, list[dict]] | None:
    loaded = load_artifact_manifest(root)
    if loaded is None:
        return None

    bundle_root, manifest = loaded
    files = artifact_deploy_files(manifest, target)
    if files is None:
        return None

    return bundle_root, files


def native_dest_path(manifest_dest: str, base_dest: str) -> str:
    if manifest_dest.startswith(("/", "~")):
        return manifest_dest
    return f"{base_dest.rstrip('/')}/{manifest_dest}"


def deploy_sim_artifacts(root: Path, *, host: str | None) -> int:
    resolved_host = host or default_ec2_host(load_config())
    loaded = load_deploy_files(root, "sim")
    if loaded is None:
        return 1

    bundle_root, files = loaded
    for entry in files:
        source = resolve_artifact_src(bundle_root, entry["src"])
        if source is None:
            return 1

        command = ["scp", "-F", str(Path.home() / ".ssh" / "config")]
        if source.is_dir():
            command.append("-r")
        command.extend([str(source), f"{resolved_host}:{entry['dest']}"])
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            return result.returncode

        mode = entry.get("mode")
        if isinstance(mode, str):
            result = subprocess.run(
                ["ssh", "-F", str(Path.home() / ".ssh" / "config"), resolved_host, "chmod", mode, entry["dest"]],
                check=False,
            )
            if result.returncode != 0:
                return result.returncode

    return 0


def deploy_native_artifacts(root: Path, *, serial: str | None, dest: str) -> int:
    loaded = load_deploy_files(root, "native")
    if loaded is None:
        return 1

    bundle_root, files = loaded
    for entry in files:
        source = resolve_artifact_src(bundle_root, entry["src"])
        if source is None:
            return 1

        target_dest = native_dest_path(entry["dest"], dest)
        command = ["adb"]
        if serial:
            command.extend(["-s", serial])
        command.extend(["push", str(source), target_dest])
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            return result.returncode

        mode = entry.get("mode")
        if isinstance(mode, str):
            command = ["adb"]
            if serial:
                command.extend(["-s", serial])
            command.extend(["shell", "chmod", mode, target_dest])
            result = subprocess.run(command, check=False)
            if result.returncode != 0:
                return result.returncode

    return 0


def run_sim_command(
    command: str,
    *,
    host: str | None = None,
    settings: str | None = None,
    profile_name: str | None = None,
    port_forward: bool = True,
    stop_port_forward: bool = True,
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


def run_terminal_request(
    *,
    command_parts: Sequence[str],
    command_text: str | None = None,
    title: str,
    cwd: str | None,
) -> int:
    command = command_text.strip() if command_text else " ".join(command_parts).strip()
    if command.startswith("-- "):
        command = command[3:].strip()
    if not command:
        print("実行するコマンドを指定してください。", file=sys.stderr)
        return 1

    request_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    request_id = f"{request_id}-{uuid.uuid4().hex[:8]}"
    request_dir = CONFIG_PATH.parent / "terminal-requests"
    request_dir.mkdir(parents=True, exist_ok=True)

    request_path = request_dir / f"{request_id}.json"
    request = {
        "id": request_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "cwd": str(Path(cwd).resolve() if cwd else Path.cwd()),
        "command": command,
    }
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"VSCode terminal request を作成しました: {request_path}")
    return 0


def run_setup(no_install: bool = False, ec2_host: str | None = None) -> int:
    providers = discover_environment_providers()
    if not providers:
        print("接続環境プロバイダが見つかりません。", file=sys.stderr)
        return 1

    print(style("AgentCockpit の接続環境を初期化します。", BOLD, CYAN))
    print(style("確認対象の状況を確認し、必要な項目を設定します。", DIM))
    print()
    config = load_config()
    print_terminal_bridge_status(offer_install=not no_install)
    print()
    configure_default_ec2_host(config, ec2_host=ec2_host)
    print()
    while True:
        categories = print_provider_overview(providers, config)
        category = select_setup_category(categories, config)
        if category is None:
            break

        provider = select_provider_for_category(category, config)
        if provider is None:
            break

        result = ensure_provider_dependencies(provider, no_install=no_install)
        if result == 0:
            config["selected_providers"][provider.category_id] = provider.provider_id
            save_config(config)
        print()

    missing_categories = unconfigured_categories(providers, config)
    print()
    if missing_categories:
        print(style("未完了のセットアップ:", BOLD, RED))
        for category_name in missing_categories:
            print(f"  - {style(category_name, RED)}")
        return 1

    print(style("初期化が完了しました。", BOLD, GREEN))
    return 0


def print_terminal_bridge_status(*, offer_install: bool) -> None:
    installed_path = installed_vscode_terminal_bridge_path()
    print(style("VSCode Terminal Bridge:", BOLD, BLUE))

    if installed_path is not None:
        print(f"  {style('導入済み', GREEN)} {style(str(installed_path), DIM)}")
        return

    print(f"  {style('未導入', YELLOW)}")
    print(f"     {style('AI が VSCode の見える terminal へ実行要求を送るための拡張です。', DIM)}")

    if not offer_install or not sys.stdin.isatty():
        print(f"     {style('導入するには make init を実行してください。', DIM)}")
        return

    answer = safe_input(
        "VSCode Terminal Bridge をインストールしますか？ [Y/n]: ",
        default_on_eof="n",
    ).lower()
    if answer not in ("", "y", "yes"):
        print(f"     {style('あとで make init で導入できます。', DIM)}")
        return

    if install_vscode_terminal_bridge() == 0:
        print(style("VSCode Terminal Bridge をインストールしました。VSCode window を reload してください。", GREEN))
    else:
        print(style("VSCode Terminal Bridge のインストールに失敗しました。", RED))


def installed_vscode_terminal_bridge_path() -> Path | None:
    extension_dir_name = f"{VSCODE_EXT_NAME}-{VSCODE_EXT_VERSION}"
    candidates = (
        Path.home() / ".vscode-server" / "extensions" / extension_dir_name,
        Path.home() / ".vscode" / "extensions" / extension_dir_name,
    )

    for path in candidates:
        if path.exists():
            return path

    return None


def install_vscode_terminal_bridge() -> int:
    src = PROJECT_ROOT / "tools" / "vscode-agentcockpit"
    dest = Path.home() / ".vscode-server" / "extensions" / f"{VSCODE_EXT_NAME}-{VSCODE_EXT_VERSION}"
    try:
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest)
    except OSError:
        return 1
    return 0


def configure_default_ec2_host(config: dict, *, ec2_host: str | None) -> None:
    current_host = default_ec2_host(config)

    if ec2_host:
        set_default_ec2_host(config, ec2_host)
        save_config(config)
        print(f"Runtime host: {style(ec2_host, BOLD, GREEN)}")
        return

    print(style("Simulation Runtime:", BOLD, BLUE))
    print(f"  既定 host: {style(current_host, BOLD)}")

    if not sys.stdin.isatty():
        return

    answer = safe_input(
        "agp sim の既定 runtime host を入力してください "
        f"[{current_host}]: ",
        default_on_eof=current_host,
    )
    selected_host = answer or current_host
    if selected_host != current_host:
        set_default_ec2_host(config, selected_host)
        save_config(config)
        print(f"  {style('更新しました:', GREEN)} {selected_host}")


def ensure_provider_dependencies(
    provider: type[DevEnvironment],
    *,
    no_install: bool = False,
) -> int:
    missing = provider.missing_commands()

    print()
    print(
        "選択: "
        f"{style(provider.display_name, BOLD)} "
        f"{style(f'({provider.provider_id})', DIM)}"
    )

    if not missing:
        print(style("必要なコマンドはすべて見つかりました。", GREEN))
        return 0

    print(style("不足しているコマンド:", BOLD, YELLOW))
    for command in missing:
        print(f"  - {style(command, YELLOW)}")

    if no_install:
        print()
        print(provider.install_hint(missing))
        return 1

    print()
    answer = safe_input(
        "不足コマンドのインストール/案内を実行しますか？ [Y/n]: ",
        default_on_eof="n",
    )
    if answer.lower() in ("", "y", "yes"):
        result = provider.install_dependencies(missing)
        if result != 0:
            return result

        remaining = provider.missing_commands()
        if remaining:
            print()
            print(style("まだ不足しているコマンド:", BOLD, RED))
            for command in remaining:
                print(f"  - {style(command, RED)}")
            return 1

        print()
        print(style("必要なコマンドはすべて見つかりました。", GREEN))
        return 0

    print(provider.install_hint(missing))
    return 1


def print_provider_overview(
    providers: Sequence[type[DevEnvironment]],
    config: dict[str, dict[str, str]],
) -> list[tuple[str, str, list[type[DevEnvironment]]]]:
    print(style("確認対象の状況:", BOLD, BLUE))
    print()

    categories: list[tuple[str, str, list[type[DevEnvironment]]]] = []
    selected_providers = config["selected_providers"]

    for category_index, (_, category_name, grouped) in enumerate(
        grouped_providers(providers)
    ):
        category_number = len(categories) + 1
        categories.append((grouped[0].category_id, category_name, grouped))
        if category_index > 0:
            print()

        print(style(f"{category_number}. {category_name}", BOLD, CYAN))

        selected = provider_by_id(grouped, selected_providers.get(grouped[0].category_id))
        if selected is not None:
            missing = selected.missing_commands()
            status = _provider_status_text(missing)
            print(
                f"  {status} "
                f"{style(selected.display_name, BOLD)} "
                f"{style(f'({selected.provider_id})', DIM)}"
            )
            print(f"     {style(selected.description, DIM)}")
            print(f"     {style('必要:', BLUE)} {_dependency_summary(selected)}")
            continue

        print(f"  {style('未設定', BOLD, YELLOW)}")
        print(f"     {style('この項目を選ぶと利用する環境を選択できます。', DIM)}")

    print()
    return categories


def select_setup_category(
    categories: Sequence[tuple[str, str, list[type[DevEnvironment]]]],
    config: dict[str, dict[str, str]],
) -> tuple[str, str, list[type[DevEnvironment]]] | None:
    default_index = first_unconfigured_category_index(categories, config)
    if default_index is None:
        prompt = "設定する項目番号を入力してください (Enter/qで終了): "
    else:
        default_category = categories[default_index - 1]
        prompt = (
            "設定する項目番号を入力してください "
            f"[{default_index}: {default_category[1]}] "
            "(qで終了): "
        )

    while True:
        raw = safe_input(prompt)
        if raw == "":
            if default_index is None:
                return None
            return categories[default_index - 1]
        if raw.lower() in ("q", "quit", "exit"):
            return None

        try:
            selected = int(raw)
        except ValueError:
            print(style("番号で入力してください。終了する場合は q を入力してください。", YELLOW))
            continue

        if 1 <= selected <= len(categories):
            return categories[selected - 1]

        print(style(f"1 から {len(categories)} の番号を入力してください。", YELLOW))


def select_provider_for_category(
    category: tuple[str, str, list[type[DevEnvironment]]],
    config: dict[str, dict[str, str]],
) -> type[DevEnvironment] | None:
    category_id, category_name, providers = category
    selected = provider_by_id(providers, config["selected_providers"].get(category_id))

    if selected is not None:
        if selected.missing_commands():
            return selected

        print()
        print(
            f"{style(category_name, BOLD, CYAN)} は "
            f"{style(selected.display_name, BOLD)} で設定済みです。"
        )
        answer = safe_input(
            "別の環境に変更しますか？ [y/N]: ",
            default_on_eof="n",
        ).lower()
        if answer not in ("y", "yes"):
            return None

    print()
    print(style(f"[{category_name}]", BOLD, CYAN))
    print(style("利用する環境を選択してください:", BOLD))
    print()

    for index, provider in enumerate(providers, start=1):
        print(f"  {style(str(index) + '.', BOLD)} {style(provider.display_name, BOLD)}")
        print(f"     {style(provider.description, DIM)}")
        print(f"     {style('必要:', BLUE)} {_dependency_summary(provider)}")
        print()

    while True:
        raw = safe_input("番号を入力してください [1]: ")
        if raw == "":
            return providers[0]

        try:
            selected_index = int(raw)
        except ValueError:
            print(style("番号で入力してください。", YELLOW))
            continue

        if 1 <= selected_index <= len(providers):
            return providers[selected_index - 1]

        print(style(f"1 から {len(providers)} の番号を入力してください。", YELLOW))


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return default_config()

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_config()

    selected_providers = data.get("selected_providers")
    if not isinstance(selected_providers, dict):
        selected_providers = {}

    ec2 = data.get("ec2")
    ec2_host = None
    if isinstance(ec2, dict) and isinstance(ec2.get("host"), str):
        ec2_host = ec2["host"]

    return {
        "selected_providers": {
            str(category_id): str(provider_id)
            for category_id, provider_id in selected_providers.items()
        },
        "ec2": {"host": ec2_host or "vibecode-graviton"},
    }


def save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def default_config() -> dict:
    return {
        "selected_providers": {},
        "ec2": {"host": "vibecode-graviton"},
    }


def default_ec2_host(config: dict) -> str:
    ec2 = config.get("ec2")
    if isinstance(ec2, dict) and isinstance(ec2.get("host"), str) and ec2["host"]:
        return ec2["host"]
    return "vibecode-graviton"


def set_default_ec2_host(config: dict, host: str) -> None:
    ec2 = config.setdefault("ec2", {})
    if not isinstance(ec2, dict):
        ec2 = {}
        config["ec2"] = ec2
    ec2["host"] = host


def unconfigured_categories(
    providers: Sequence[type[DevEnvironment]],
    config: dict[str, dict[str, str]],
) -> list[str]:
    missing: list[str] = []
    selected_providers = config["selected_providers"]

    for category_id, category_name, grouped in grouped_providers(providers):
        selected = provider_by_id(grouped, selected_providers.get(category_id))
        if selected is None or selected.missing_commands():
            missing.append(category_name)

    return missing


def first_unconfigured_category_index(
    categories: Sequence[tuple[str, str, list[type[DevEnvironment]]]],
    config: dict[str, dict[str, str]],
) -> int | None:
    selected_providers = config["selected_providers"]

    for index, (category_id, _, providers) in enumerate(categories, start=1):
        selected = provider_by_id(providers, selected_providers.get(category_id))
        if selected is None or selected.missing_commands():
            return index

    return None


def grouped_providers(
    providers: Sequence[type[DevEnvironment]],
) -> list[tuple[str, str, list[type[DevEnvironment]]]]:
    groups: list[tuple[str, str, list[type[DevEnvironment]]]] = []

    for provider in providers:
        if groups and groups[-1][0] == provider.category_id:
            groups[-1][2].append(provider)
        else:
            groups.append((provider.category_id, provider.category_name, [provider]))

    return groups


def provider_by_id(
    providers: Sequence[type[DevEnvironment]],
    provider_id: str | None,
) -> type[DevEnvironment] | None:
    if provider_id is None:
        return None

    for provider in providers:
        if provider.provider_id == provider_id:
            return provider
    return None


def _dependency_summary(provider: type[DevEnvironment]) -> str:
    statuses = provider.dependency_status()
    if not statuses:
        return style("なし", DIM)
    return ", ".join(
        _dependency_status_text(status.name, status.installed)
        for status in statuses
    )


def _provider_status_text(missing: list[str]) -> str:
    if missing:
        return style("未設定", BOLD, YELLOW)
    return style("設定済み", BOLD, GREEN)


def _dependency_status_text(name: str, installed: bool) -> str:
    if installed:
        return f"{name}({style('OK', GREEN)})"
    return f"{name}({style('未インストール', YELLOW)})"
