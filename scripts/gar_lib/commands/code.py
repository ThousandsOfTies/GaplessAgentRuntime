"""`gar code` subcommand: Codespace connection and VS Code terminal profile."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path

from scripts.gar_lib.access.codespaces import codespace_list_rows, select_codespace_from_list
from scripts.gar_lib.commands.action_surface import hide_compatibility_parsers, validate_action_options
from scripts.gar_lib.commands.capabilities import add_capability_options
from scripts.gar_lib.commands.code_connection import (
    detect_codespace_workspace,
    gh_timeout_seconds,
    install_codespace_ssh_config,
    mount_codespace_code,
    print_completed_stderr,
    remote_path_exists,
    run_gh_captured,
    unmount_codespace_code,
)
from scripts.gar_lib.commands.code_observation import code_logs, observe_code, prepare_code
from scripts.gar_lib.commands.code_state import (
    CodespaceConnectionState,
    codespace_state_path,
    codespace_terminal_script,
    load_connection_state,
    load_legacy_codespace_state,
)
from scripts.gar_lib.commands.result import render_observation
from scripts.gar_lib.commands.workspace_resolver import resolve_workspace
from scripts.gar_lib.core.command import GarCommand
from scripts.gar_lib.core.command_surface import CODE_HOST_ACTIONS
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.vscode.profile_manage import (
    remove_vscode_terminal_profile,
    write_vscode_terminal_profile,
)

DEFAULT_CODESPACE_REMOTE_PATH = "/workspaces/gar-build-env"


def _is_windows_host() -> bool:
    return os.name == "nt"


@dataclass(frozen=True)
class CodeStartOptions:
    """Inputs resolved before ``gar code start`` performs any external work."""

    home: Path
    codespace_name: str | None
    remote_path: str
    mount_dir: Path
    settings_path: Path
    profile_name: str
    state_path: Path
    terminal_path: Path
    no_mount: bool
    gh_timeout: int | None


def _add_workspace_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        default=argparse.SUPPRESS,
        metavar="NAME",
        help="gar config で登録した product workspace 名",
    )


def _add_codespace_argument(parser: argparse.ArgumentParser, *, purpose: str) -> None:
    parser.add_argument(
        "--target",
        "--codespace",
        dest="codespace",
        default=None,
        metavar="TARGET",
        help=f"{purpose} development target 名",
    )


def add_code_parser(
    subparsers: argparse._SubParsersAction,
) -> dict[str, argparse.ArgumentParser]:
    parser = subparsers.add_parser(
        "code",
        help="Build Artifacts workspace との接続を管理します",
    )
    commands = parser.add_subparsers(dest="code_command", metavar="action")
    parser.epilog = "互換: code boot / shutdown は code start host / stop host と同じ操作です。"
    add_capability_options(parser, group="code")

    boot_parser = commands.add_parser("boot", help="development target を起動します")
    _add_workspace_argument(boot_parser)
    _add_codespace_argument(boot_parser, purpose="起動する")

    start_parser = commands.add_parser(
        "start",
        help="Codespace build workspaceへのSSH接続を準備します",
    )
    _add_workspace_argument(start_parser)
    _add_codespace_argument(start_parser, purpose="接続する")
    start_parser.add_argument("--remote-path", default=None, help="Codespace 側 workspace path")
    start_parser.add_argument("--mount-dir", default=None, help="POSIX host側のsshfs mount path")
    start_parser.add_argument("--settings", default=None, help="VS Code settings.json path")
    start_parser.add_argument("--profile-name", default=None, help="VS Code terminal profile 名")
    start_parser.add_argument(
        "--no-mount",
        action="store_true",
        help="sshfs mount を更新せず、SSH 設定と terminal profile だけ更新します",
    )

    stop_parser = commands.add_parser(
        "stop",
        help="Codespace build workspaceのlocal接続を停止します",
    )
    _add_workspace_argument(stop_parser)
    _add_codespace_argument(stop_parser, purpose="停止する")
    stop_parser.add_argument("--mount-dir", default=None, help="POSIX host側のsshfs mount path")
    stop_parser.add_argument("--settings", default=None, help="VS Code settings.json path")
    stop_parser.add_argument("--profile-name", default=None, help="VS Code terminal profile 名")
    stop_parser.add_argument(
        "--shutdown",
        action="store_true",
        help="local接続の後片付け後にGitHub Codespace VMも停止します",
    )

    shutdown_parser = commands.add_parser("shutdown", help="development target を停止します")
    _add_workspace_argument(shutdown_parser)
    _add_codespace_argument(shutdown_parser, purpose="停止する")

    status_parser = commands.add_parser("status", help="Codespace VM / 接続状態を確認します")
    _add_workspace_argument(status_parser)
    _add_codespace_argument(status_parser, purpose="確認する")
    status_parser.add_argument("--mount-dir", default=None, help="POSIX host側のsshfs mount path")
    for action_parser in (start_parser, stop_parser):
        action_parser.add_argument(
            "code_subject",
            nargs="?",
            choices=("session", "host"),
            default="session",
            metavar="subject",
            help="対象: session（既定: local接続） / host（Codespace VM）",
        )
        scoped_options = {}
        for option in action_parser._actions:
            if option.option_strings and option.dest not in {"help", "workspace", "codespace"}:
                option.default = argparse.SUPPRESS
                option.help = f"{option.help}（session 専用）"
                scoped_options[option.dest] = (option.option_strings[0], {"session"})
        action_parser.set_defaults(_gar_scoped_options=scoped_options)
    hide_compatibility_parsers(commands, ("boot", "shutdown"))
    for action, description in (
        ("prepare", "開発用tool・workspace・認証の前提条件を検証します（VM起動・設定変更なし）"),
        ("log", "Codespaceの作成logを取得します"),
        ("diag", "開発環境のhostと接続を診断します（停止中VMは起動しません）"),
    ):
        leaf = commands.add_parser(action, help=description)
        _add_workspace_argument(leaf)
        _add_codespace_argument(leaf, purpose="操作する")
    for leaf in commands.choices.values():
        leaf.add_argument(
            "--json",
            dest="json_output",
            action="store_true",
            default=argparse.SUPPRESS,
            help="結果を単一JSONで表示します",
        )
    return {"code": parser}


def run_code_cli(args: Namespace, *, help_parser: argparse.ArgumentParser) -> int:
    if args.code_command is None:
        help_parser.print_help()
        return 1
    if args.code_command in {"prepare", "diag", "log", "status"}:
        try:
            workspace = resolve_workspace(getattr(args, "workspace", None))
            args._gar_workspace = workspace
            codespace = getattr(args, "codespace", None)
            if args.code_command == "log":
                return code_logs(workspace, codespace=codespace)
            report = (
                prepare_code(workspace, codespace=codespace)
                if args.code_command == "prepare"
                else observe_code(
                    workspace, action=args.code_command, codespace=codespace, mount_dir=getattr(args, "mount_dir", None)
                )
            )
            return render_observation(report, json_output=getattr(args, "json_output", False))
        except (GarDomainError, OSError, ValueError) as error:
            print(f"gar: {error}", file=sys.stderr)
            return 1
    command = args.code_command
    subject = getattr(args, "code_subject", None)
    try:
        validate_action_options(args, command=GarCommand("code", subject, command))
    except GarDomainError as error:
        print(f"gar: {error}", file=sys.stderr)
        return 1
    if subject == "host":
        command = CODE_HOST_ACTIONS[command]
    resolved = {}
    if getattr(args, "json_output", False):
        args._gar_workspace = resolve_workspace(getattr(args, "workspace", None))
        resolved["workspace"] = args._gar_workspace
    return run_code_command(
        command,
        workspace_selector=getattr(args, "workspace", None),
        codespace=getattr(args, "codespace", None),
        remote_path=getattr(args, "remote_path", None),
        mount_dir=getattr(args, "mount_dir", None),
        settings=getattr(args, "settings", None),
        profile_name=getattr(args, "profile_name", None),
        no_mount=getattr(args, "no_mount", False),
        shutdown=getattr(args, "shutdown", False),
        **resolved,
    )


def run_code_command(
    command: str,
    *,
    workspace_selector: str | None = None,
    codespace: str | None = None,
    remote_path: str | None = None,
    mount_dir: str | None = None,
    settings: str | None = None,
    profile_name: str | None = None,
    no_mount: bool = False,
    shutdown: bool = False,
    gh_timeout: int | None = None,
    workspace: Workspace | None = None,
) -> int:
    try:
        workspace = workspace or resolve_workspace(workspace_selector)
    except GarDomainError as error:
        print(f"gar code {command}: {error}", file=sys.stderr)
        return 1

    environment_id = workspace.selected_environments.codespace or "local"
    if environment_id == "local":
        return run_local_code_command(command)
    if environment_id == "github_codespaces":
        connection_codespace = _workspace_codespace_name(workspace)
        connection_remote_path = _workspace_remote_path(workspace)
        selected_codespace = codespace or connection_codespace
        selected_remote_path = remote_path or connection_remote_path
        if command == "boot":
            return boot_code_codespace(codespace=selected_codespace, gh_timeout=gh_timeout)
        if command == "start":
            return start_code_codespace(
                codespace=selected_codespace,
                remote_path=selected_remote_path,
                mount_dir=mount_dir,
                settings=settings,
                profile_name=profile_name,
                no_mount=no_mount,
                gh_timeout=gh_timeout,
            )
        if command == "stop":
            return stop_code_codespace(
                codespace=selected_codespace,
                mount_dir=mount_dir,
                settings=settings,
                profile_name=profile_name,
                shutdown=shutdown,
                gh_timeout=gh_timeout,
            )
        if command == "shutdown":
            return shutdown_code_codespace(codespace=selected_codespace, gh_timeout=gh_timeout)
        if command == "status":
            return status_code_codespace(
                codespace=selected_codespace,
                mount_dir=mount_dir,
                gh_timeout=gh_timeout,
            )

    print(
        f"gar code {command}: 現在のsetupでは対応する開発環境が見つかりません。\n"
        f"  development: {environment_id}\n"
        "  `gar config` でLocalまたはGitHub Codespacesを選択してください。",
        file=sys.stderr,
    )
    return 1


def _workspace_codespace_name(workspace: Workspace) -> str | None:
    if workspace.connection_type != "codespaces":
        return None
    return workspace.connection.codespace


def _workspace_remote_path(workspace: Workspace) -> str | None:
    if workspace.connection_type != "codespaces":
        return None
    return workspace.connection.path.rstrip("/") or None


def run_local_code_command(command: str) -> int:
    if command in ("boot", "start"):
        print("Local development environment is already available.")
        return 0
    if command in ("stop", "shutdown"):
        print("Local development environment does not need to be stopped.")
        return 0
    if command == "status":
        print("Local development environment: available")
        return 0
    print(
        f"gar code {command}: Local development environmentでは未対応です。",
        file=sys.stderr,
    )
    return 1


def boot_code_codespace(
    *,
    codespace: str | None = None,
    gh_timeout: int | None = None,
) -> int:
    if shutil.which("gh") is None:
        print("gar code start host: missing required command: gh", file=sys.stderr)
        return 1
    if shutil.which("ssh") is None:
        print("gar code start host: missing required command: ssh", file=sys.stderr)
        return 1

    selected_gh_timeout = gh_timeout_seconds(gh_timeout, command_name="gar code start host")
    selected_codespace = select_code_codespace(
        codespace,
        command_name="gar code start host",
        gh_timeout=selected_gh_timeout,
    )
    if not selected_codespace:
        return 1

    print(f"Starting Codespace VM: {selected_codespace}")
    result = run_gh_captured(
        ["gh", "codespace", "ssh", "-c", selected_codespace, "--", "true"],
        timeout=selected_gh_timeout,
        label=f"start Codespace {selected_codespace}",
        command_name="gar code start host",
    )
    if result is None:
        return 1
    if result.returncode != 0:
        print_completed_stderr(result)
        return result.returncode

    print(f"Codespace VM is reachable: {selected_codespace}")
    return 0


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
    options = resolve_code_start_options(
        codespace=codespace,
        remote_path=remote_path,
        mount_dir=mount_dir,
        settings=settings,
        profile_name=profile_name,
        no_mount=no_mount,
        gh_timeout=gh_timeout,
    )
    if not validate_code_start_options(options):
        return 1

    selected_codespace = select_code_codespace(
        options.codespace_name,
        command_name="gar code start",
        gh_timeout=options.gh_timeout,
        home=options.home,
    )
    if selected_codespace is None:
        return 1
    if not _is_safe_command_value(selected_codespace) or selected_codespace.startswith("-"):
        print(f"gar code start: invalid Codespace name: {selected_codespace!r}", file=sys.stderr)
        return 1

    ssh_host = configure_codespace_ssh(
        home=options.home,
        codespace=selected_codespace,
        gh_timeout=options.gh_timeout,
    )
    if ssh_host is None:
        return 1

    try:
        selected_remote_path = resolve_codespace_remote_path(
            selected_codespace,
            options.remote_path,
            gh_timeout=options.gh_timeout,
        )
    except subprocess.TimeoutExpired:
        timeout_text = "without a timeout" if options.gh_timeout is None else f"after {options.gh_timeout}s"
        print(
            f"gar code start: timed out {timeout_text} while checking the remote workspace",
            file=sys.stderr,
        )
        return 1
    if not _is_safe_command_value(selected_remote_path):
        print(f"gar code start: invalid remote path: {selected_remote_path!r}", file=sys.stderr)
        return 1
    state = CodespaceConnectionState(
        codespace_name=selected_codespace,
        ssh_host=ssh_host,
        remote_path=selected_remote_path,
        mount_dir=options.mount_dir,
    )

    if not options.no_mount:
        mount_result = mount_codespace_code(
            host=state.ssh_host,
            remote_path=state.remote_path,
            mount_dir=state.mount_dir,
        )
        if mount_result != 0:
            return mount_result

    try:
        state.write(options.state_path)
    except (OSError, ValueError) as error:
        if not options.no_mount:
            expected_source = f"{state.ssh_host}:{state.remote_path}"
            unmount_codespace_code(
                mount_dir=state.mount_dir,
                expected_source=expected_source,
            )
        print(f"gar code start: could not update local configuration: {error}", file=sys.stderr)
        return 1

    try:
        configure_vscode_codespace(options)
    except (OSError, ValueError) as error:
        print(f"gar code start: could not update VS Code configuration: {error}", file=sys.stderr)
        return 1

    report_codespace_start(options, state)
    return 0


def resolve_code_start_options(
    *,
    codespace: str | None,
    remote_path: str | None,
    mount_dir: str | None,
    settings: str | None,
    profile_name: str | None,
    no_mount: bool,
    gh_timeout: int | None,
) -> CodeStartOptions:
    """Resolve CLI and environment values without performing external work."""

    home = Path.home()
    selected_remote_path = remote_path or os.environ.get(
        "CODESPACE_REMOTE_PATH",
        DEFAULT_CODESPACE_REMOTE_PATH,
    )
    selected_mount_dir = (
        Path(mount_dir if mount_dir is not None else default_codespaces_mount_dir()).expanduser().resolve()
    )
    default_settings = (
        Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "Code" / "User" / "settings.json"
        if _is_windows_host()
        else home / ".vscode-server" / "data" / "Machine" / "settings.json"
    )
    settings_path = (
        Path(
            settings
            or os.environ.get(
                "CODESPACE_SETTINGS",
                str(default_settings),
            )
        )
        .expanduser()
        .resolve()
    )

    return CodeStartOptions(
        home=home,
        codespace_name=codespace or os.environ.get("CODESPACE_NAME"),
        remote_path=selected_remote_path,
        mount_dir=selected_mount_dir,
        settings_path=settings_path,
        profile_name=profile_name or os.environ.get("CODESPACE_PROFILE_NAME", "Codespaces"),
        state_path=codespace_state_path(home),
        terminal_path=home / ".local" / "bin" / "codespace-terminal",
        # Windows keeps the Product workspace local and reaches Codespaces by
        # SSH; its standard flow does not depend on WinFsp/SSHFS mounts.
        no_mount=no_mount or _is_windows_host(),
        gh_timeout=gh_timeout_seconds(gh_timeout),
    )


def validate_code_start_options(options: CodeStartOptions) -> bool:
    """Validate input values and commands before writing local configuration."""

    named_values = {
        "Codespace name": options.codespace_name,
        "remote path": options.remote_path,
        "mount path": str(options.mount_dir),
        "settings path": str(options.settings_path),
        "profile name": options.profile_name,
    }
    for label, value in named_values.items():
        if value is not None and not _is_safe_command_value(value):
            print(f"gar code start: invalid {label}: {value!r}", file=sys.stderr)
            return False

    required_commands = ["gh", "ssh"]
    if not options.no_mount:
        required_commands.extend(["sshfs", "findmnt", "mountpoint"])
        if shutil.which("fusermount3") is None and shutil.which("fusermount") is None:
            print(
                "gar code start: missing required command: fusermount3 or fusermount",
                file=sys.stderr,
            )
            return False

    for command_name in required_commands:
        if shutil.which(command_name) is None:
            print(f"gar code start: missing required command: {command_name}", file=sys.stderr)
            return False
    return True


def configure_codespace_ssh(
    *,
    home: Path,
    codespace: str,
    gh_timeout: int | None,
) -> str | None:
    """Fetch and install SSH configuration for one Codespace."""

    print(f"Fetching SSH config for Codespace: {codespace}")
    config_result = run_gh_captured(
        ["gh", "codespace", "ssh", "-c", codespace, "--config"],
        timeout=gh_timeout,
        label=f"generate SSH config for Codespace {codespace}",
    )
    if config_result is None:
        return None
    if config_result.returncode != 0:
        print_completed_stderr(config_result)
        return None

    try:
        host = install_codespace_ssh_config(home, config_result.stdout)
    except OSError as error:
        print(f"gar code start: could not write SSH config: {error}", file=sys.stderr)
        return None
    if host is None:
        print("gar code start: could not find a concrete Host in SSH config", file=sys.stderr)
    return host


def resolve_codespace_remote_path(
    codespace: str,
    requested_path: str,
    *,
    gh_timeout: int | None,
) -> str:
    """Use the requested directory when present, otherwise try workspace discovery."""

    if remote_path_exists(codespace, requested_path, timeout=gh_timeout):
        return requested_path

    detected_path = detect_codespace_workspace(codespace, timeout=gh_timeout)
    if detected_path is None:
        return requested_path

    print(f"Remote path not found: {requested_path}")
    print(f"Using detected Codespace workspace: {detected_path}")
    return detected_path


def configure_vscode_codespace(options: CodeStartOptions) -> None:
    """Install the terminal launcher and its VS Code profile."""

    options.terminal_path.parent.mkdir(parents=True, exist_ok=True)
    options.terminal_path.write_text(codespace_terminal_script(), encoding="utf-8")
    options.terminal_path.chmod(0o755)
    if _is_windows_host():
        write_vscode_terminal_profile(
            options.settings_path,
            options.profile_name,
            Path(sys.executable),
            arguments=[str(options.terminal_path)],
        )
    else:
        write_vscode_terminal_profile(
            options.settings_path,
            options.profile_name,
            options.terminal_path,
        )


def report_codespace_start(
    options: CodeStartOptions,
    state: CodespaceConnectionState,
) -> None:
    print(f"Codespace: {state.codespace_name}")
    print(f"SSH host:  {state.ssh_host}")
    print(f"Remote:    {state.remote_path}")
    print(f"Mount:     {'not used' if options.no_mount else state.mount_dir}")
    print(f"State:     {options.state_path}")
    print(f"Terminal:  {options.terminal_path}")
    print(f"Profile:   {options.profile_name}")


def stop_code_codespace(
    *,
    codespace: str | None = None,
    mount_dir: str | None = None,
    settings: str | None = None,
    profile_name: str | None = None,
    shutdown: bool = False,
    gh_timeout: int | None = None,
) -> int:
    home = Path.home()
    state_file = codespace_state_path(home)
    state = load_connection_state(home)

    selected_mount_dir = Path(
        mount_dir
        or os.environ.get("CODESPACE_MOUNT_DIR")
        or (str(state.mount_dir) if state else None)
        or str(default_codespaces_mount_dir())
    ).expanduser()
    default_settings = (
        Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "Code" / "User" / "settings.json"
        if _is_windows_host()
        else home / ".vscode-server" / "data" / "Machine" / "settings.json"
    )
    settings_path = Path(
        settings
        or os.environ.get(
            "CODESPACE_SETTINGS",
            str(default_settings),
        )
    ).expanduser()
    selected_profile_name = profile_name or os.environ.get(
        "CODESPACE_PROFILE_NAME",
        "Codespaces",
    )

    expected_source = f"{state.ssh_host}:{state.remote_path}" if state else None

    unmount_result = (
        0
        if _is_windows_host()
        else unmount_codespace_code(
            mount_dir=selected_mount_dir,
            expected_source=expected_source,
        )
    )
    profile_result = remove_vscode_terminal_profile(settings_path, selected_profile_name)

    if state_file.exists():
        print(f"State:     kept {state_file}")
    print("SSH config: kept ~/.ssh/codespaces and Include entry")

    shutdown_result = 0
    if shutdown:
        shutdown_result = shutdown_code_codespace(
            codespace=codespace,
            state=state,
            gh_timeout=gh_timeout,
        )

    return unmount_result or profile_result or shutdown_result


def shutdown_code_codespace(
    *,
    codespace: str | None = None,
    state: CodespaceConnectionState | None = None,
    gh_timeout: int | None = None,
) -> int:
    saved_state = state or load_connection_state(Path.home())
    selected_codespace = (
        codespace
        or os.environ.get("GAR_CODESPACE_NAME")
        or os.environ.get("CODESPACE_NAME")
        or (saved_state.codespace_name if saved_state else None)
    )
    selected_gh_timeout = gh_timeout_seconds(gh_timeout, command_name="gar code stop host")

    if not selected_codespace:
        list_result = run_gh_captured(
            ["gh", "codespace", "list"],
            timeout=selected_gh_timeout,
            label="list Codespaces",
            command_name="gar code stop host",
        )
        if list_result is None:
            return 1
        if list_result.returncode != 0:
            print_completed_stderr(list_result)
            return list_result.returncode
        selected_codespace = select_codespace_from_list(list_result.stdout)

    if not selected_codespace:
        print("gar code stop host: no Codespace found", file=sys.stderr)
        print("Pass one explicitly: gar code stop host --codespace NAME", file=sys.stderr)
        return 1

    print(f"Stopping Codespace VM: {selected_codespace}")
    result = run_gh_captured(
        ["gh", "codespace", "stop", "-c", selected_codespace],
        timeout=selected_gh_timeout,
        label=f"stop Codespace {selected_codespace}",
        command_name="gar code stop host",
    )
    if result is None:
        return 1
    if result.returncode != 0:
        print_completed_stderr(result)
        return result.returncode
    return 0


def status_code_codespace(
    *,
    codespace: str | None = None,
    mount_dir: str | None = None,
    gh_timeout: int | None = None,
) -> int:
    if shutil.which("gh") is None:
        print("gar code status: missing required command: gh", file=sys.stderr)
        return 1

    selected_gh_timeout = gh_timeout_seconds(gh_timeout, command_name="gar code status")
    result = run_gh_captured(
        ["gh", "codespace", "list"],
        timeout=selected_gh_timeout,
        label="list Codespaces",
        command_name="gar code status",
    )
    if result is None:
        return 1
    if result.returncode != 0:
        print_completed_stderr(result)
        return result.returncode

    saved_state = load_connection_state(Path.home())
    selected_codespace = (
        codespace
        or os.environ.get("GAR_CODESPACE_NAME")
        or os.environ.get("CODESPACE_NAME")
        or (saved_state.codespace_name if saved_state else None)
    )
    rows = codespace_list_rows(result.stdout)
    if selected_codespace:
        rows = [fields for fields in rows if fields and fields[0] == selected_codespace]

    if rows:
        for fields in rows:
            print("\t".join(fields))
    else:
        print("gar code status: no matching Codespace found", file=sys.stderr)
        return 1

    selected_mount_dir = Path(
        mount_dir or (str(saved_state.mount_dir) if saved_state else None) or str(default_codespaces_mount_dir())
    ).expanduser()
    if _is_windows_host():
        print("Mount: not used on Windows (SSH terminal profile only)")
    elif shutil.which("mountpoint") is not None:
        mounted = subprocess.run(["mountpoint", "-q", str(selected_mount_dir)], check=False).returncode == 0
        print(f"Mount: {'mounted' if mounted else 'not mounted'} at {selected_mount_dir}")
    else:
        print(f"Mount: unknown at {selected_mount_dir} (missing mountpoint)")

    return 0


def select_code_codespace(
    codespace: str | None,
    *,
    command_name: str,
    gh_timeout: int | None,
    home: Path | None = None,
) -> str | None:
    selected_codespace = codespace or os.environ.get("GAR_CODESPACE_NAME") or os.environ.get("CODESPACE_NAME")
    if selected_codespace:
        return selected_codespace

    saved_state = load_connection_state(home or Path.home())
    if saved_state is not None and saved_state.codespace_name:
        return saved_state.codespace_name

    list_result = run_gh_captured(
        ["gh", "codespace", "list"],
        timeout=gh_timeout,
        label="list Codespaces",
        command_name=command_name,
    )
    if list_result is None:
        return None
    if list_result.returncode != 0:
        print_completed_stderr(list_result)
        return None

    selected_codespace = select_codespace_from_list(list_result.stdout)
    if not selected_codespace:
        print(f"{command_name}: no Codespace found", file=sys.stderr)
        print(f"Pass one explicitly: {command_name} --codespace NAME", file=sys.stderr)
        return None
    return selected_codespace


def load_codespace_state(state_file: Path) -> dict[str, str]:
    """Compatibility name for readers of the former shell-style state file."""

    return load_legacy_codespace_state(state_file)


def default_codespaces_mount_dir() -> Path:
    return Path.cwd() / "codespaces"


def _is_safe_command_value(value: str) -> bool:
    return bool(value) and "\0" not in value and "\n" not in value and "\r" not in value
