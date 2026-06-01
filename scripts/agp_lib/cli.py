"""`agp` CLI entry point. Argument parsing and dispatch only.

Implementation lives in sibling submodules:
- :mod:`scripts.agp_lib._ui` — color / safe_input helpers
- :mod:`scripts.agp_lib._config` — config IO, paths, EC2 host helpers
- :mod:`scripts.agp_lib._vscode` — VSCode terminal profile / Bridge install
- :mod:`scripts.agp_lib._code` — ``agp code``
- :mod:`scripts.agp_lib._deploy` — ``agp sim deploy`` / ``agp native deploy``
- :mod:`scripts.agp_lib._sim` — ``agp sim``
- :mod:`scripts.agp_lib._terminal` — ``agp terminal``
- :mod:`scripts.agp_lib._setup` — ``agp setup``
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

# Re-exports — keep public surface stable for callers and tests.
from scripts.agp_lib._code import (  # noqa: F401
    codespace_list_rows,
    codespace_terminal_script,
    detect_codespace_workspace,
    first_ssh_host,
    load_codespace_state,
    mount_codespace_code,
    remote_path_exists,
    run_code_command,
    select_codespace_from_list,
    start_code_codespace,
    stop_code_codespace,
    unmount_codespace_code,
)
from scripts.agp_lib._config import (  # noqa: F401
    CONFIG_PATH,
    PROJECT_ROOT,
    VSCODE_EXT_NAME,
    VSCODE_EXT_VERSION,
    default_config,
    default_ec2_host,
    load_config,
    save_config,
    set_default_ec2_host,
)
from scripts.agp_lib._deploy import (  # noqa: F401
    artifact_deploy_files,
    default_artifacts_dir,
    deploy_native_artifacts,
    deploy_native_artifacts_ssh,
    deploy_sim_artifacts,
    find_artifact_manifest,
    load_artifact_manifest,
    load_deploy_files,
    native_dest_path,
    resolve_artifact_src,
    run_deploy_command,
    selected_device_provider_id,
)
from scripts.agp_lib._setup import (  # noqa: F401
    configure_default_ec2_host,
    ensure_provider_dependencies,
    first_unconfigured_category_index,
    grouped_providers,
    print_provider_overview,
    print_terminal_bridge_status,
    provider_by_id,
    run_setup,
    select_provider_for_category,
    select_setup_category,
    unconfigured_categories,
)
from scripts.agp_lib._sim import (  # noqa: F401
    run_sim_command,
    show_sim_state,
    sim_terminal_script,
    start_sim_port_forward,
    status_sim_port_forward,
    stop_sim_port_forward,
    write_sim_terminal_profile,
)
from scripts.agp_lib._terminal import (  # noqa: F401
    run_terminal_gc,
    run_terminal_request,
)
from scripts.agp_lib._ui import (  # noqa: F401
    BLUE,
    BOLD,
    CYAN,
    DIM,
    GREEN,
    RED,
    RESET,
    YELLOW,
    safe_input,
    style,
)
from scripts.agp_lib._vscode import (  # noqa: F401
    install_vscode_terminal_bridge,
    installed_vscode_terminal_bridge_path,
    remove_vscode_terminal_profile,
    write_vscode_terminal_profile,
)
from scripts.agp_lib.environments.discovery import (  # noqa: F401
    discover_environment_providers,
)


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
    code_start_parser.add_argument("--codespace", default=None, help="接続する Codespace 名")
    code_start_parser.add_argument("--remote-path", default=None, help="Codespace 側 workspace path")
    code_start_parser.add_argument("--mount-dir", default=None, help="WSL 側 sshfs mount path")
    code_start_parser.add_argument("--settings", default=None, help="VS Code settings.json path")
    code_start_parser.add_argument("--profile-name", default=None, help="VS Code terminal profile 名")
    code_start_parser.add_argument(
        "--no-mount",
        action="store_true",
        help="sshfs mount を更新せず、SSH 設定と terminal profile だけ更新します",
    )
    code_stop_parser = code_subparsers.add_parser(
        "stop",
        help="Codespace build workspace の WSL hub 側接続を停止します",
    )
    code_stop_parser.add_argument("--mount-dir", default=None, help="WSL 側 sshfs mount path")
    code_stop_parser.add_argument("--settings", default=None, help="VS Code settings.json path")
    code_stop_parser.add_argument("--profile-name", default=None, help="VS Code terminal profile 名")

    terminal_parser = subparsers.add_parser(
        "terminal",
        help="VSCode integrated terminal への実行要求を作成します",
    )
    terminal_subparsers = terminal_parser.add_subparsers(dest="terminal_command")
    terminal_run_parser = terminal_subparsers.add_parser(
        "run",
        help="VSCode integrated terminal でコマンドを実行します",
    )
    terminal_run_parser.add_argument("--title", default="AgentCockpit", help="VSCode terminal の表示名")
    terminal_run_parser.add_argument("--cwd", default=None, help="コマンドを実行する作業ディレクトリ")
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
    terminal_gc_parser = terminal_subparsers.add_parser(
        "gc",
        help="terminal-requests/processed と terminal-status の古いエントリを削除します",
    )
    terminal_gc_parser.add_argument("--keep-days", type=int, default=7, help="保持する日数 (既定: 7)")
    terminal_gc_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="削除対象を表示するだけで実際には削除しません",
    )

    sim_parser = subparsers.add_parser("sim", help="simulation runtime を操作します")
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
            command_parser.add_argument("--settings", default=None, help="VS Code settings.json path")
            command_parser.add_argument("--profile-name", default=None, help="VS Code terminal profile 名")
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
        "--host",
        default=None,
        help="SSH/scp provider 利用時の SSH config 上の host 名",
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
    if args.command == "terminal" and args.terminal_command == "gc":
        return run_terminal_gc(keep_days=args.keep_days, dry_run=args.dry_run)
    if args.command == "terminal":
        terminal_parser.print_help()
        return 1
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
                host=args.host,
                dest=args.dest,
            )

    parser.print_help()
    return 0
