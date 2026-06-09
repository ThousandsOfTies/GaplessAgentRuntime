"""`gar` CLI entry point. Argument parsing and dispatch only.

Implementation lives in sibling submodules:
- :mod:`scripts.gar_lib._ui` — color / safe_input helpers
- :mod:`scripts.gar_lib._config` — config IO, paths, EC2 host helpers
- :mod:`scripts.gar_lib._vscode` — VSCode terminal profile / Bridge install
- :mod:`scripts.gar_lib._code` — ``gar code``
- :mod:`scripts.gar_lib._deploy` — ``gar sim env deploy`` / ``gar target deploy``
- :mod:`scripts.gar_lib._ec2` — ``gar sim boot`` / ``shutdown`` / ``status``
- :mod:`scripts.gar_lib._hw` — ``gar hw``
- :mod:`scripts.gar_lib._sim` — ``gar sim``
- :mod:`scripts.gar_lib._terminal` — ``gar terminal``
- :mod:`scripts.gar_lib._usb` — ``gar usb``
- :mod:`scripts.gar_lib._setup` — ``gar setup``
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

# Re-exports — keep public surface stable for callers and tests.
from scripts.gar_lib._code import (  # noqa: F401
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
from scripts.gar_lib._config import (  # noqa: F401
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
from scripts.gar_lib._deploy import (  # noqa: F401
    DEFAULT_CODESPACE_ARTIFACT_ROOT,
    adb_device_available,
    artifact_deploy_files,
    artifact_manifest_deploy_sources,
    default_artifacts_dir,
    default_codespace_artifact_root,
    deploy_target_artifacts,
    deploy_target_artifacts_ssh,
    deploy_sim_artifacts,
    ensure_adb_device,
    fetch_codespace_artifacts,
    find_artifact_manifest,
    gh_codespace_cp,
    load_artifact_manifest,
    load_deploy_files,
    target_dest_path,
    resolve_artifact_src,
    run_deploy_command,
    run_target_sync_command,
    select_codespace,
    selected_device_provider_id,
)
from scripts.gar_lib._ec2 import (  # noqa: F401
    ec2_instance_state,
    ec2_public_ip,
    run_ec2_command,
    update_ssh_config_hostname,
)
from scripts.gar_lib._hw import (  # noqa: F401
    HW_TEMPLATE_FILES,
    run_hw_command,
    write_hw_template,
)
from scripts.gar_lib._setup import (  # noqa: F401
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
from scripts.gar_lib._sim import (  # noqa: F401
    run_gpio_sim_check,
    run_sim_command,
    run_sim_diag_json,
    run_sim_gpio_command,
    run_sim_panel,
    show_sim_state,
    sim_terminal_script,
    start_sim_port_forward,
    status_sim_port_forward,
    stop_sim_port_forward,
    write_sim_terminal_profile,
)
from scripts.gar_lib._terminal import (  # noqa: F401
    run_terminal_gc,
    run_terminal_request,
)
from scripts.gar_lib._ui import (  # noqa: F401
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
from scripts.gar_lib._usb import (  # noqa: F401
    UsbDevice,
    list_usb_devices,
    parse_usbipd_list,
    run_usb_command,
)
from scripts.gar_lib._vscode import (  # noqa: F401
    install_vscode_terminal_bridge,
    installed_vscode_terminal_bridge_path,
    remove_vscode_terminal_profile,
    write_vscode_terminal_profile,
)
from scripts.gar_lib.environments.discovery import (  # noqa: F401
    discover_environment_providers,
)

SIM_VM_COMMAND_MAP = {
    "boot": "start",
    "shutdown": "stop",
    "status": "status",
}


def normalize_question_help(argv: Sequence[str] | None = None) -> list[str]:
    """Treat `?` before `--` as a context-local argparse help request."""

    args = list(sys.argv[1:] if argv is None else argv)
    scan_end = args.index("--") if "--" in args else len(args)
    for index, value in enumerate(args[:scan_end]):
        if value == "?":
            return [*args[:index], "--help", *args[index + 1 :]]
    return args


def completion_bash_script() -> str:
    return """# Gapless Agent Runtime bash completion.
if command -v register-python-argcomplete >/dev/null 2>&1 && python -c 'import argcomplete' >/dev/null 2>&1; then
  eval "$(register-python-argcomplete gar)"
else
  _agp_completion() {
    local IFS=$'\\n'
    COMPREPLY=($(COMP_LINE="$COMP_LINE" COMP_POINT="$COMP_POINT" "$1" completion words --cword "$COMP_CWORD" -- "${COMP_WORDS[@]}"))
  }
  complete -o nosort -F _agp_completion gar
fi
"""


def enable_argcomplete(parser: argparse.ArgumentParser) -> None:
    try:
        import argcomplete
    except ImportError:
        return
    argcomplete.autocomplete(parser)


def _subparser_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _parser_options(parser: argparse.ArgumentParser) -> list[str]:
    options: list[str] = []
    for action in parser._actions:
        options.extend(action.option_strings)
    return options


def parser_completion_words(cword: int, words: Sequence[str]) -> list[str]:
    """Return shell completion candidates from argparse parser structure."""

    parser = build_parser()
    current = words[cword] if cword < len(words) else ""
    tokens = list(words[1:cword])

    index = 0
    while index < len(tokens):
        token = tokens[index]
        subparsers = _subparser_action(parser)
        if subparsers and token in subparsers.choices:
            parser = subparsers.choices[token]
            index += 1
            continue
        if token.startswith("-"):
            option_action = parser._option_string_actions.get(token)
            if option_action and option_action.nargs in (None, 1) and index + 1 < len(tokens):
                index += 2
                continue
        index += 1

    candidates = _parser_options(parser)
    subparsers = _subparser_action(parser)
    if subparsers:
        candidates.extend(subparsers.choices)

    return sorted(candidate for candidate in candidates if candidate.startswith(current))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gar")
    subparsers = parser.add_subparsers(dest="command", metavar="command")

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
        help="gar sim が既定で使う SSH config 上の runtime host 名",
    )
    code_parser = subparsers.add_parser(
        "code",
        help="Build Artifacts workspace との接続を管理します",
    )
    code_subparsers = code_parser.add_subparsers(dest="code_command", metavar="command")
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
    terminal_subparsers = terminal_parser.add_subparsers(dest="terminal_command", metavar="command")
    terminal_run_parser = terminal_subparsers.add_parser(
        "run",
        help="VSCode integrated terminal でコマンドを実行します",
    )
    terminal_run_parser.add_argument("--title", default="Gapless Agent Runtime", help="VSCode terminal の表示名")
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
        help="実行するコマンド。例: gar terminal run -- gar setup",
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

    completion_parser = subparsers.add_parser(
        "completion",
        help="shell completion script を出力します",
    )
    completion_subparsers = completion_parser.add_subparsers(dest="completion_shell", metavar="shell")
    completion_subparsers.add_parser("bash", help="bash completion script を出力します")
    completion_words_parser = completion_subparsers.add_parser(
        "words",
        help=argparse.SUPPRESS,
    )
    completion_words_parser.add_argument("--cword", type=int, required=True)
    completion_words_parser.add_argument("words", nargs=argparse.REMAINDER)

    sim_parser = subparsers.add_parser("sim", help="simulation VM / services / virtual H/W を操作します")
    sim_subparsers = sim_parser.add_subparsers(dest="sim_command", metavar="command")
    for sim_vm_command_name, ec2_command_name in SIM_VM_COMMAND_MAP.items():
        help_text = {
            "boot": "simulation VM を起動します",
            "shutdown": "simulation VM を停止します",
            "status": "simulation VM の状態を確認します",
        }[sim_vm_command_name]
        sim_vm_command_parser = sim_subparsers.add_parser(
            sim_vm_command_name,
            help=help_text,
        )
        sim_vm_command_parser.add_argument(
            "--host",
            default=None,
            help="SSH config 上の host 名。省略時は .gar/config.json の保存済み host",
        )
        sim_vm_command_parser.add_argument(
            "--instance-id",
            default=None,
            help="EC2 instance ID。省略時は保存済み設定",
        )
        sim_vm_command_parser.add_argument(
            "--region",
            default=None,
            help="AWS region。省略時は保存済み設定",
        )
        if ec2_command_name == "start":
            sim_vm_command_parser.add_argument(
                "--no-update-ssh",
                action="store_true",
                help="起動後に ~/.ssh/config の HostName を更新しません",
            )
            sim_vm_command_parser.add_argument(
                "--pull",
                action="store_true",
                help="起動後に ec2.repo_dir で git pull を実行します",
            )

    sim_env_parser = sim_subparsers.add_parser(
        "env",
        help="simulation services を配置・起動・停止・診断します",
    )
    sim_env_subparsers = sim_env_parser.add_subparsers(dest="sim_env_command", metavar="command")
    sim_deploy_parser = sim_env_subparsers.add_parser(
        "deploy",
        help="simulation 環境インフラ（CUSE stubs / web-bridge）を VM へ配置します（artifact.json の deploy.sim_env セクション）",
    )
    sim_deploy_parser.add_argument(
        "--host",
        default=None,
        help="SSH config 上の runtime host 名。省略時は .gar/config.json の保存済み host",
    )
    sim_deploy_parser.add_argument(
        "--artifacts-dir",
        default=None,
        help="Codespace から WSL hub へコピー済みの成果物 root",
    )

    sim_app_deploy_parser = sim_subparsers.add_parser(
        "deploy",
        help="target app を VM へ転送します（artifact.json の deploy.sim セクション）",
    )
    sim_app_deploy_parser.add_argument(
        "--host",
        default=None,
        help="SSH config 上の runtime host 名。省略時は .gar/config.json の保存済み host",
    )
    sim_app_deploy_parser.add_argument(
        "--artifacts-dir",
        default=None,
        help="Codespace から WSL hub へコピー済みの成果物 root",
    )
    for command_name in ("start", "stop", "status", "diag", "log", "gpio-sim-check"):
        command_parser = sim_env_subparsers.add_parser(
            command_name,
            help=f"simulation services: {command_name}",
        )
        command_parser.add_argument(
            "--host",
            default=None,
            help="SSH config 上の runtime host 名。省略時は .gar/config.json の保存済み host",
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
        if command_name in ("status", "diag", "gpio-sim-check"):
            command_parser.add_argument(
                "--json",
                dest="json_output",
                action="store_true",
                help="結果を機械可読な JSON で出力します（AI / CI 向け）",
            )

    sim_infra_parser = sim_subparsers.add_parser(
        "infra", help="simulation host インフラを Terraform で管理します（要実装）"
    )
    sim_infra_subparsers = sim_infra_parser.add_subparsers(dest="infra_command", metavar="command")
    for _infra_cmd in ("plan", "apply", "destroy", "output"):
        _p = sim_infra_subparsers.add_parser(_infra_cmd, help=f"terraform {_infra_cmd}")
        _p.add_argument("--key-name", default=None, help="EC2 SSH key pair name")
        _p.add_argument("--region", default=None, help="AWS region")
        _p.add_argument("--auto-approve", action="store_true", help="--auto-approve を terraform に渡します")

    sim_gpio_parser = sim_subparsers.add_parser(
        "gpio", help="GPIO dummy runtime を生成・配置・確認します"
    )
    sim_gpio_subparsers = sim_gpio_parser.add_subparsers(dest="gpio_command", metavar="command")
    for gpio_command_name in ("plan", "install", "start", "stop", "status"):
        gpio_command_parser = sim_gpio_subparsers.add_parser(
            gpio_command_name,
            help=f"GPIO runtime: {gpio_command_name}",
        )
        if gpio_command_name != "plan":
            gpio_command_parser.add_argument(
                "--host",
                default=None,
                help="SSH config 上の runtime host 名。省略時は .gar/config.json の保存済み host",
            )
        if gpio_command_name in ("plan", "status"):
            gpio_command_parser.add_argument(
                "--json",
                dest="json_output",
                action="store_true",
                help="結果を機械可読な JSON で出力します（AI / CI 向け）",
            )

    # --- 仮想パネル / 仮想ディスプレイへの操作（旧 make panel-* の置き換え） ---
    def _add_host_arg(parser):
        parser.add_argument(
            "--host",
            default=None,
            help="SSH config 上の runtime host 名。省略時は .gar/config.json の保存済み host",
        )

    sim_ui_parser = sim_subparsers.add_parser(
        "ui", help="Virtual Hardware UI / API を操作します"
    )
    sim_ui_subparsers = sim_ui_parser.add_subparsers(dest="ui_command", metavar="command")

    sim_button_parser = sim_ui_subparsers.add_parser(
        "button", help="仮想 GPIO ボタンを操作します"
    )
    sim_button_subparsers = sim_button_parser.add_subparsers(dest="panel_action", metavar="command")
    sim_button_press = sim_button_subparsers.add_parser(
        "press", help="ボタンを押して離します"
    )
    sim_button_press.add_argument("line", type=int, help="GPIO line 番号（例: 17）")
    sim_button_press.add_argument(
        "--duration-ms", type=int, default=150, help="押下時間（ミリ秒）"
    )
    _add_host_arg(sim_button_press)
    sim_button_set = sim_button_subparsers.add_parser(
        "set", help="ボタンの状態を直接セットします"
    )
    sim_button_set.add_argument("line", type=int, help="GPIO line 番号（例: 17）")
    sim_button_set.add_argument("value", type=int, help="0=離す / 1=押す")
    _add_host_arg(sim_button_set)

    sim_rfid_parser = sim_ui_subparsers.add_parser(
        "rfid", help="仮想 RFID カードを操作します"
    )
    sim_rfid_subparsers = sim_rfid_parser.add_subparsers(dest="panel_action", metavar="command")
    sim_rfid_tap = sim_rfid_subparsers.add_parser("tap", help="カードを置きます")
    sim_rfid_tap.add_argument("uid", help="カード UID（例: 04:AB:CD:EF:01:23）")
    _add_host_arg(sim_rfid_tap)
    sim_rfid_remove = sim_rfid_subparsers.add_parser("remove", help="カードを外します")
    _add_host_arg(sim_rfid_remove)

    sim_range_parser = sim_ui_subparsers.add_parser(
        "range", help="仮想 VL53L0X の距離値を操作します"
    )
    sim_range_subparsers = sim_range_parser.add_subparsers(dest="panel_action", metavar="command")
    sim_range_set = sim_range_subparsers.add_parser("set", help="距離値をセットします")
    sim_range_set.add_argument("value", type=int, help="距離（ミリメートル）")
    _add_host_arg(sim_range_set)

    target_parser = subparsers.add_parser(
        "target",
        help="接続先が提供する I/O を使う runtime を操作します",
    )
    target_subparsers = target_parser.add_subparsers(dest="target_command", metavar="command")
    target_deploy_parser = target_subparsers.add_parser(
        "deploy",
        help="target runtime へ成果物を配置します",
    )
    target_deploy_parser.add_argument(
        "--serial",
        default=None,
        help="adb device serial。省略時は adb の既定接続先",
    )
    target_deploy_parser.add_argument(
        "--host",
        default=None,
        help="SSH/scp provider 利用時の SSH config 上の host 名",
    )
    target_deploy_parser.add_argument(
        "--dest",
        default="/home/user",
        help="artifact.json の target dest が相対パスのときの接続先基準ディレクトリ",
    )
    target_deploy_parser.add_argument(
        "--artifacts-dir",
        default=None,
        help="Codespace から WSL hub へコピー済みの成果物 root",
    )
    target_fetch_parser = target_subparsers.add_parser(
        "fetch",
        help="Codespace の artifact bundle を WSL hub へ取得します",
    )
    target_fetch_parser.add_argument(
        "--codespace",
        default=None,
        help="取得元 Codespace 名。省略時は GAR_CODESPACE_NAME / CODESPACE_NAME / gh list",
    )
    target_fetch_parser.add_argument(
        "--remote-root",
        default=None,
        help=f"Codespace 上の artifact bundle root（既定: {DEFAULT_CODESPACE_ARTIFACT_ROOT}）",
    )
    target_fetch_parser.add_argument(
        "--artifacts-dir",
        default=None,
        help="WSL hub 側に保存する artifact bundle root",
    )
    target_sync_parser = target_subparsers.add_parser(
        "sync",
        help="Codespace から成果物を取得し、target runtime へ配置します",
    )
    target_sync_parser.add_argument(
        "--codespace",
        default=None,
        help="取得元 Codespace 名。省略時は GAR_CODESPACE_NAME / CODESPACE_NAME / gh list",
    )
    target_sync_parser.add_argument(
        "--remote-root",
        default=None,
        help=f"Codespace 上の artifact bundle root（既定: {DEFAULT_CODESPACE_ARTIFACT_ROOT}）",
    )
    target_sync_parser.add_argument(
        "--artifacts-dir",
        default=None,
        help="WSL hub 側に保存する artifact bundle root",
    )
    target_sync_parser.add_argument(
        "--serial",
        default=None,
        help="adb device serial。省略時は adb の既定接続先",
    )
    target_sync_parser.add_argument(
        "--host",
        default=None,
        help="SSH/scp provider 利用時の SSH config 上の host 名",
    )
    target_sync_parser.add_argument(
        "--dest",
        default="/home/user",
        help="artifact.json の target dest が相対パスのときの接続先基準ディレクトリ",
    )

    usb_parser = subparsers.add_parser(
        "usb",
        help="USB-C 実機を usbipd-win 経由で WSL2 に attach します",
    )
    usb_subparsers = usb_parser.add_subparsers(dest="usb_command", metavar="command")
    for usb_command_name in ("attach", "detach", "status", "list"):
        usb_command_parser = usb_subparsers.add_parser(
            usb_command_name,
            help=f"USB: {usb_command_name}",
        )
        if usb_command_name != "list":
            usb_command_parser.add_argument(
                "--busid",
                default=None,
                help="usbipd の busid。省略時は保存済み busid → Android 自動検出",
            )
        if usb_command_name == "attach":
            usb_command_parser.add_argument(
                "--no-remember",
                action="store_true",
                help="attach した busid を .gar/config.json に記憶しません",
            )

    hw_parser = subparsers.add_parser(
        "hw",
        help="hardware 定義 CSV を管理します",
    )
    hw_subparsers = hw_parser.add_subparsers(dest="hw_command", metavar="command")
    hw_init_parser = hw_subparsers.add_parser(
        "init",
        help="空の hardware 定義 CSV テンプレートを作成します",
    )
    hw_init_parser.add_argument(
        "--dir",
        dest="output_dir",
        default=None,
        help="CSV を作成するディレクトリ（既定: Gapless Agent Runtime/hardware）",
    )
    hw_init_parser.add_argument(
        "--force",
        action="store_true",
        help="既存のテンプレート CSV を上書きします",
    )
    parser._agp_subcommand_parsers = {  # type: ignore[attr-defined]
        "code": code_parser,
        "terminal": terminal_parser,
        "completion": completion_parser,
        "sim": sim_parser,
        "sim_env": sim_env_parser,
        "sim_infra": sim_infra_parser,
        "sim_gpio": sim_gpio_parser,
        "sim_ui": sim_ui_parser,
        "sim_button": sim_button_parser,
        "sim_rfid": sim_rfid_parser,
        "sim_range": sim_range_parser,
        "target": target_parser,
        "usb": usb_parser,
        "hw": hw_parser,
    }
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    subcommand_parsers = parser._agp_subcommand_parsers  # type: ignore[attr-defined]
    enable_argcomplete(parser)
    try:
        args = parser.parse_args(normalize_question_help(argv))
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        raise

    if args.command == "setup":
        return run_setup(no_install=args.no_install, ec2_host=args.ec2_host)
    if args.command == "code":
        if args.code_command is None:
            subcommand_parsers["code"].print_help()
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
        subcommand_parsers["terminal"].print_help()
        return 1
    if args.command == "completion":
        if args.completion_shell == "bash":
            print(completion_bash_script(), end="")
            return 0
        if args.completion_shell == "words":
            words = args.words[1:] if args.words[:1] == ["--"] else args.words
            print("\n".join(parser_completion_words(args.cword, words)))
            return 0
        subcommand_parsers["completion"].print_help()
        return 1
    if args.command == "sim":
        if args.sim_command is None:
            subcommand_parsers["sim"].print_help()
            return 1
        if args.sim_command in SIM_VM_COMMAND_MAP:
            return run_ec2_command(
                SIM_VM_COMMAND_MAP[args.sim_command],
                host=args.host,
                instance_id=args.instance_id,
                region=args.region,
                update_ssh=not getattr(args, "no_update_ssh", False),
                pull=getattr(args, "pull", False),
            )
        if args.sim_command == "deploy":
            return run_deploy_command(
                "sim",
                artifacts_dir=getattr(args, "artifacts_dir", None),
                host=getattr(args, "host", None),
            )
        if args.sim_command == "env":
            if args.sim_env_command is None:
                subcommand_parsers["sim_env"].print_help()
                return 1
            if args.sim_env_command == "deploy":
                return run_deploy_command(
                    "sim_env",
                    artifacts_dir=args.artifacts_dir,
                    host=args.host,
                )
            return run_sim_command(
                args.sim_env_command,
                host=args.host,
                settings=getattr(args, "settings", None),
                profile_name=getattr(args, "profile_name", None),
                port_forward=not getattr(args, "no_port_forward", False),
                stop_port_forward=not getattr(args, "keep_port_forward", False),
                json_output=getattr(args, "json_output", False),
            )
        if args.sim_command == "infra":
            if args.infra_command is None:
                subcommand_parsers["sim_infra"].print_help()
                return 1
            print(
                f"error: gar sim infra {args.infra_command} は未実装です。\n"
                "  実装方針: infra/terraform/main.tf の terraform コマンドを呼び出し、\n"
                "  apply 後に出力される instance_id / public_ip を .gar/config.json へ保存し、\n"
                "  ~/.ssh/config の HostName を更新する（gar sim boot --pull 相当の後処理も行う）。\n"
                "  infra/terraform/ を整備後に実装してください。",
                file=__import__("sys").stderr,
            )
            return 1
        if args.sim_command == "gpio":
            if args.gpio_command is None:
                subcommand_parsers["sim_gpio"].print_help()
                return 1
            return run_sim_gpio_command(
                args.gpio_command,
                host=getattr(args, "host", None),
                json_output=getattr(args, "json_output", False),
            )
        if args.sim_command == "ui":
            if args.ui_command is None:
                subcommand_parsers["sim_ui"].print_help()
                return 1
            if args.ui_command == "button":
                if args.panel_action == "press":
                    return run_sim_panel(
                        "button-press",
                        host=args.host,
                        line=args.line,
                        duration_ms=args.duration_ms,
                    )
                if args.panel_action == "set":
                    return run_sim_panel(
                        "button-set",
                        host=args.host,
                        line=args.line,
                        value=args.value,
                    )
                subcommand_parsers["sim_button"].print_help()
                return 1
            if args.ui_command == "rfid":
                if args.panel_action == "tap":
                    return run_sim_panel("rfid-tap", host=args.host, uid=args.uid)
                if args.panel_action == "remove":
                    return run_sim_panel("rfid-remove", host=args.host)
                subcommand_parsers["sim_rfid"].print_help()
                return 1
            if args.ui_command == "range":
                if args.panel_action == "set":
                    return run_sim_panel("range-set", host=args.host, value=args.value)
                subcommand_parsers["sim_range"].print_help()
                return 1
            subcommand_parsers["sim_ui"].print_help()
            return 1
        subcommand_parsers["sim"].print_help()
        return 1
    if args.command == "target":
        if args.target_command is None:
            subcommand_parsers["target"].print_help()
            return 1
        if args.target_command == "deploy":
            return run_deploy_command(
                "target",
                artifacts_dir=args.artifacts_dir,
                serial=args.serial,
                host=args.host,
                dest=args.dest,
            )
        if args.target_command == "fetch":
            root = (
                default_artifacts_dir()
                if args.artifacts_dir is None
                else Path(args.artifacts_dir).expanduser()
            )
            return fetch_codespace_artifacts(
                root.resolve(),
                codespace=args.codespace,
                remote_root=args.remote_root,
            )
        if args.target_command == "sync":
            return run_target_sync_command(
                artifacts_dir=args.artifacts_dir,
                codespace=args.codespace,
                remote_root=args.remote_root,
                serial=args.serial,
                host=args.host,
                dest=args.dest,
            )

    if args.command == "usb":
        if args.usb_command is None:
            subcommand_parsers["usb"].print_help()
            return 1
        return run_usb_command(
            args.usb_command,
            busid=getattr(args, "busid", None),
            remember=not getattr(args, "no_remember", False),
        )

    if args.command == "hw":
        if args.hw_command is None:
            subcommand_parsers["hw"].print_help()
            return 1
        return run_hw_command(
            args.hw_command,
            output_dir=args.output_dir,
            force=args.force,
        )

    parser.print_help()
    return 0
