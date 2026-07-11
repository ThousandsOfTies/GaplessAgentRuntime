"""`gar` CLI entry point. Argument parsing and dispatch only.

Implementation lives in sibling submodules:
- :mod:`scripts.gar_lib.vscode.terminal_ui` — color / safe_input helpers
- :mod:`scripts.gar_lib.config` — config IO, paths, EC2 host helpers
- :mod:`scripts.gar_lib.vscode.profile_manage` — VSCode terminal profile write/remove
- :mod:`scripts.gar_lib.vscode.terminal_bridge` — VSCode Terminal Bridge extension install
- :mod:`scripts.gar_lib.commands.code` — ``gar code``
- :mod:`scripts.gar_lib.artifacts.manifest` — artifact.json 共通基盤・Codespace fetch（CLI引数に対応しないドメインロジック）
- :mod:`scripts.gar_lib.commands.target` — ``gar target``
- :mod:`scripts.gar_lib.commands.hw` — ``gar hw``
- :mod:`scripts.gar_lib.commands.infra` — ``gar sim infra``
- :mod:`scripts.gar_lib.commands.shim` — ``gar shim``
- :mod:`scripts.gar_lib.commands.sim` — ``gar sim``
- :mod:`scripts.gar_lib.commands.terminal` — ``gar terminal``
- :mod:`scripts.gar_lib.commands.usb` — ``gar usb``
- :mod:`scripts.gar_lib.commands.setup` — ``gar setup``
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from scripts.gar_lib.artifacts.manifest import (  # noqa: F401
    DEFAULT_CODESPACE_ARTIFACT_ROOT,
    artifact_deploy_files,
    artifact_manifest_deploy_sources,
    default_artifacts_dir,
    default_codespace_artifact_root,
    fetch_codespace_artifacts,
    find_artifact_manifest,
    gh_codespace_cp,
    load_artifact_manifest,
    load_deploy_files,
    resolve_artifact_src,
    select_codespace,
    target_dest_path,
)

# Re-exports — keep public surface stable for callers and tests.
from scripts.gar_lib.commands.code import (  # noqa: F401
    boot_code_codespace,
    codespace_list_rows,
    codespace_terminal_script,
    detect_codespace_workspace,
    first_ssh_host,
    load_codespace_state,
    mount_codespace_code,
    remote_path_exists,
    run_code_command,
    select_codespace_from_list,
    shutdown_code_codespace,
    start_code_codespace,
    status_code_codespace,
    stop_code_codespace,
    unmount_codespace_code,
)
from scripts.gar_lib.commands.hw import (  # noqa: F401
    HW_TEMPLATE_FILES,
    run_hw_command,
    write_hw_template,
)
from scripts.gar_lib.commands.infra import run_sim_infra_command  # noqa: F401
from scripts.gar_lib.commands.setup import (  # noqa: F401
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
from scripts.gar_lib.commands.shim import run_shim_command  # noqa: F401
from scripts.gar_lib.commands.sim import (  # noqa: F401
    deploy_sim_artifacts,
    run_gpio_sim_check,
    run_product_sim_build,
    run_sim_command,
    run_sim_deploy_command,
    run_sim_diag_json,
    run_sim_env_build_command,
    run_sim_gpio_command,
    run_sim_host_command,
    show_sim_state,
    sim_terminal_script,
    start_sim_port_forward,
    status_sim_port_forward,
    stop_sim_port_forward,
    write_sim_terminal_profile,
)
from scripts.gar_lib.commands.target import (  # noqa: F401
    adb_device_available,
    deploy_target_artifacts,
    deploy_target_artifacts_ssh,
    ensure_adb_device,
    run_target_build_command,
    run_target_deploy_command,
    run_target_flash_command,
    selected_target_provider_id,
)
from scripts.gar_lib.commands.terminal import (  # noqa: F401
    run_terminal_gc,
    run_terminal_request,
)
from scripts.gar_lib.commands.usb import (  # noqa: F401
    UsbDevice,
    list_usb_devices,
    parse_usbipd_list,
    run_usb_command,
)
from scripts.gar_lib.config import (  # noqa: F401
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
from scripts.gar_lib.environments.discovery import (  # noqa: F401
    discover_environment_providers,
)
from scripts.gar_lib.environments.registry.simulator.aws_ec2 import (  # noqa: F401
    ec2_instance_state,
    ec2_public_ip,
    run_ec2_command,
    update_ssh_config_hostname,
)
from scripts.gar_lib.environments.registry.target.esp32_esptool import (  # noqa: F401
    ensure_esptool_python,
    esp32_serial_port_access_error,
    normalize_esp32_serial_port,
    run_esp32_flash_command,
    validate_esp32_artifact,
    verify_esp32_artifact_checksums,
)
from scripts.gar_lib.targets.esp32 import (  # noqa: F401
    DEFAULT_ESP32_ARTIFACT_ROOT,
    DEFAULT_ESP32_CODESPACE_PROJECT_ROOT,
    DEFAULT_ESP32_PIO_ENV,
    fetch_esp32_codespace_artifact,
    find_latest_esp32_artifact,
    parse_esp32_build_artifact_path,
    resolve_esp32_artifact_dir,
    run_esp32_build_command,
)
from scripts.gar_lib.vscode.profile_manage import (  # noqa: F401
    remove_vscode_terminal_profile,
    write_vscode_terminal_profile,
)
from scripts.gar_lib.vscode.terminal_bridge import (  # noqa: F401
    install_vscode_terminal_bridge,
    installed_vscode_terminal_bridge_path,
)
from scripts.gar_lib.vscode.terminal_ui import (  # noqa: F401
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

SIM_VM_COMMAND_MAP = {
    "start": "start",
    "stop": "stop",
    "status": "status",
}

CODE_COMMAND_MAP = {
    "boot": "boot",
    "start": "start",
    "stop": "stop",
    "shutdown": "shutdown",
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


def _run_with_json_summary(command_label: str, json_output: bool, func) -> int:
    """``func`` (終了コードを返す) を実行する。``json_output`` 時は人間向けの
    進捗出力を stderr へ退避し、最後に機械可読な結果サマリ JSON を stdout へ
    1 個だけ出力する（AI / CI 向け）。"""
    if not json_output:
        return func()
    with contextlib.redirect_stdout(sys.stderr):
        exit_code = func()
    print(
        json.dumps(
            {"command": command_label, "ok": exit_code == 0, "exit_code": exit_code},
            ensure_ascii=False,
            indent=2,
        )
    )
    return exit_code


def add_code_start_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--target",
        "--codespace",
        dest="codespace",
        default=None,
        metavar="TARGET",
        help="接続する development target 名",
    )
    parser.add_argument("--remote-path", default=None, help="Codespace 側 workspace path")
    parser.add_argument("--mount-dir", default=None, help="WSL 側 sshfs mount path")
    parser.add_argument("--settings", default=None, help="VS Code settings.json path")
    parser.add_argument("--profile-name", default=None, help="VS Code terminal profile 名")
    parser.add_argument(
        "--no-mount",
        action="store_true",
        help="sshfs mount を更新せず、SSH 設定と terminal profile だけ更新します",
    )


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
    setup_parser.add_argument(
        "--esp32-port",
        default=None,
        help="ESP32 esptool provider が使う serial port を保存します（例: COM3, /dev/ttyUSB0）",
    )
    setup_parser.add_argument(
        "--workspace-root",
        default=None,
        help="local product workspace を追加します（複数指定は gar setup の対話画面で管理）",
    )
    code_parser = subparsers.add_parser(
        "code",
        help="Build Artifacts workspace との接続を管理します",
    )
    code_subparsers = code_parser.add_subparsers(dest="code_command", metavar="command")
    code_boot_parser = code_subparsers.add_parser(
        "boot",
        help="development target を起動します",
    )
    code_boot_parser.add_argument(
        "--target",
        "--codespace",
        dest="codespace",
        default=None,
        metavar="TARGET",
        help="起動する development target 名",
    )
    code_start_parser = code_subparsers.add_parser(
        "start",
        help="Codespace build workspace を WSL hub から見えるようにします",
    )
    add_code_start_arguments(code_start_parser)
    code_stop_parser = code_subparsers.add_parser(
        "stop",
        help="Codespace build workspace の WSL hub 側接続を停止します",
    )
    code_stop_parser.add_argument(
        "--target",
        "--codespace",
        dest="codespace",
        default=None,
        metavar="TARGET",
        help="停止する development target 名",
    )
    code_stop_parser.add_argument("--mount-dir", default=None, help="WSL 側 sshfs mount path")
    code_stop_parser.add_argument("--settings", default=None, help="VS Code settings.json path")
    code_stop_parser.add_argument("--profile-name", default=None, help="VS Code terminal profile 名")
    code_stop_parser.add_argument(
        "--shutdown",
        action="store_true",
        help="WSL 側接続の後片付け後に GitHub Codespace VM も停止します",
    )
    code_shutdown_parser = code_subparsers.add_parser(
        "shutdown",
        help="development target を停止します",
    )
    code_shutdown_parser.add_argument(
        "--target",
        "--codespace",
        dest="codespace",
        default=None,
        metavar="TARGET",
        help="停止する development target 名",
    )
    code_status_parser = code_subparsers.add_parser(
        "status",
        help="Codespace VM / 接続状態を確認します",
    )
    code_status_parser.add_argument(
        "--target",
        "--codespace",
        dest="codespace",
        default=None,
        metavar="TARGET",
        help="確認する development target 名",
    )
    code_status_parser.add_argument("--mount-dir", default=None, help="WSL 側 sshfs mount path")

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

    shim_parser = subparsers.add_parser(
        "shim",
        help="[非推奨: gar sim env build を使ってください] setup 済み target の simulation shim をビルドします",
    )
    shim_subparsers = shim_parser.add_subparsers(dest="shim_command", metavar="command")
    shim_build_parser = shim_subparsers.add_parser(
        "build",
        help="[非推奨: gar sim env build のエイリアス] setup 済み target/provider に対応する shim artifact をビルドします",
    )
    shim_build_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="結果を機械可読な JSON で出力します（AI / CI 向け）",
    )

    sim_parser = subparsers.add_parser("sim", help="simulation VM / services / virtual H/W を操作します")
    sim_subparsers = sim_parser.add_subparsers(dest="sim_command", metavar="command")
    sim_build_parser = sim_subparsers.add_parser(
        "build",
        help="選択した product workspace の simulation build hook を実行します",
    )
    sim_build_parser.add_argument(
        "--workspace-root",
        default=None,
        help="複数の local product workspace がある場合にビルド対象を指定します",
    )
    sim_build_parser.add_argument(
        "action",
        nargs="?",
        choices=("clean",),
        help="clean を指定すると product の simulation build artifact を削除します",
    )
    for sim_vm_command_name, ec2_command_name in SIM_VM_COMMAND_MAP.items():
        help_text = {
            "start": "simulation VM を起動します",
            "stop": "simulation VM を停止します",
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
        if sim_vm_command_name == "status":
            sim_vm_command_parser.add_argument(
                "--json",
                dest="json_output",
                action="store_true",
                help="結果を機械可読な JSON で出力します（AI / CI 向け）",
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
    sim_env_build_parser = sim_env_subparsers.add_parser(
        "build",
        help="仮想デバイススタブ（CUSE I2C/SPI など）や Wokwi firmware をビルドします",
    )
    sim_env_build_parser.add_argument(
        "--provider",
        default=None,
        help="simulation provider id を明示指定します（省略時は .gar/config.json の selected_providers.simulation）",
    )
    sim_env_build_parser.add_argument(
        "--workspace-root",
        default=None,
        help="複数の local product workspace がある場合にビルド対象を指定します",
    )
    sim_env_build_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="結果を機械可読な JSON で出力します（AI / CI 向け）",
    )
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
    sim_env_gpio_parser = sim_env_subparsers.add_parser(
        "gpio",
        help="GPIO dummy runtime を個別に生成・配置・確認します",
    )
    sim_env_gpio_subparsers = sim_env_gpio_parser.add_subparsers(dest="gpio_command", metavar="command")
    for gpio_command_name in ("plan", "install", "start", "stop", "status"):
        gpio_command_parser = sim_env_gpio_subparsers.add_parser(
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

    sim_app_deploy_parser = sim_subparsers.add_parser(
        "deploy",
        help="target app を VM へ転送します（artifact.json の deploy.app セクション）",
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
        "infra", help="simulation host インフラを Terraform で管理します"
    )
    sim_infra_subparsers = sim_infra_parser.add_subparsers(dest="infra_command", metavar="command")
    for _infra_cmd in ("setup", "apply", "destroy"):
        _p = sim_infra_subparsers.add_parser(_infra_cmd, help=f"terraform {_infra_cmd}")
        _p.add_argument("--key-name", default=None, help="EC2 SSH key pair name")
        _p.add_argument("--region", default=None, help="AWS region")
        _p.add_argument("--auto-approve", action="store_true", help="--auto-approve を terraform に渡します")

    target_parser = subparsers.add_parser(
        "target",
        help="接続先が提供する I/O を使う runtime を操作します",
    )
    target_subparsers = target_parser.add_subparsers(dest="target_command", metavar="command")
    target_build_parser = target_subparsers.add_parser(
        "build",
        help="setup 済み target の実機用 artifact をビルドします",
    )
    target_build_parser.add_argument(
        "--codespace",
        default=None,
        help="ビルド元 Codespace 名。省略時は GAR_CODESPACE_NAME / CODESPACE_NAME / gh list",
    )
    target_build_parser.add_argument(
        "--remote-project-root",
        default=DEFAULT_ESP32_CODESPACE_PROJECT_ROOT,
        help=f"Codespace 上の project root（既定: {DEFAULT_ESP32_CODESPACE_PROJECT_ROOT}）",
    )
    target_build_parser.add_argument(
        "--pio-env",
        default=DEFAULT_ESP32_PIO_ENV,
        help=f"PlatformIO environment（既定: {DEFAULT_ESP32_PIO_ENV}）",
    )
    target_build_parser.add_argument(
        "--artifact-root",
        default=None,
        help=f"WSL 側に保存する artifact root（既定: {DEFAULT_ESP32_ARTIFACT_ROOT}）",
    )
    target_deploy_parser = target_subparsers.add_parser(
        "deploy",
        help="target runtime へ成果物を配置します",
    )
    target_deploy_parser.add_argument(
        "--serial",
        default=None,
        help="adb device serial。esp32_esptool provider では serial port としても扱います",
    )
    target_deploy_parser.add_argument(
        "--port",
        default=None,
        help="esp32_esptool provider 利用時の serial port。例: /dev/ttyACM0, /dev/ttyUSB0, COM3",
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
    target_deploy_parser.add_argument(
        "--codespace",
        default=None,
        help="artifact が未取得のときの取得元 Codespace 名。省略時は GAR_CODESPACE_NAME / CODESPACE_NAME / gh list",
    )
    target_deploy_parser.add_argument(
        "--remote-root",
        default=None,
        help=f"Codespace 上の artifact bundle root（既定: {DEFAULT_CODESPACE_ARTIFACT_ROOT}）",
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
    target_build_esp32_parser = target_subparsers.add_parser(
        "build-esp32",
        help="Codespaces で ESP32/M5Stack firmware をビルドし artifact を取得します",
    )
    target_build_esp32_parser.add_argument(
        "--codespace",
        default=None,
        help="ビルド元 Codespace 名。省略時は GAR_CODESPACE_NAME / CODESPACE_NAME / gh list",
    )
    target_build_esp32_parser.add_argument(
        "--remote-project-root",
        default=DEFAULT_ESP32_CODESPACE_PROJECT_ROOT,
        help=f"Codespace 上の PlatformIO project root（既定: {DEFAULT_ESP32_CODESPACE_PROJECT_ROOT}）",
    )
    target_build_esp32_parser.add_argument(
        "--pio-env",
        default=DEFAULT_ESP32_PIO_ENV,
        help=f"PlatformIO environment（既定: {DEFAULT_ESP32_PIO_ENV}）",
    )
    target_build_esp32_parser.add_argument(
        "--artifact-root",
        default=None,
        help=f"WSL 側に保存する artifact root（既定: {DEFAULT_ESP32_ARTIFACT_ROOT}）",
    )
    target_build_esp32_parser.add_argument(
        "--flash",
        action="store_true",
        help="artifact 取得後にそのまま flash-esp32 を実行します",
    )
    target_build_esp32_parser.add_argument(
        "--port",
        default=None,
        help="--flash 時の serial port。例: /dev/ttyACM0, /dev/ttyUSB0, COM3",
    )
    target_build_esp32_parser.add_argument("--baud", type=int, default=921600, help="--flash 時の baud rate")
    target_build_esp32_parser.add_argument("--chip", default="esp32", help="--flash 時の esptool --chip 値")
    target_build_esp32_parser.add_argument(
        "--no-verify",
        action="store_true",
        help="--flash 時に SHA256SUMS 検証を省略します",
    )
    target_build_esp32_parser.add_argument(
        "--no-install-esptool",
        action="store_true",
        help="--flash 時に esptool 不在でも GAR 管理 venv へ自動導入しません",
    )
    target_flash_esp32_parser = target_subparsers.add_parser(
        "flash-esp32",
        help="ESP32/M5Stack firmware artifact を esptool で実機へ書き込みます",
    )
    target_flash_esp32_parser.add_argument(
        "--artifact-dir",
        default=None,
        help=f"書き込む artifact directory（省略時は {DEFAULT_ESP32_ARTIFACT_ROOT} の最新）",
    )
    target_flash_esp32_parser.add_argument(
        "--port",
        default=None,
        help="serial port。WSL では COM3 を /dev/ttyS3 に自動変換します",
    )
    target_flash_esp32_parser.add_argument("--baud", type=int, default=921600, help="書き込み baud rate")
    target_flash_esp32_parser.add_argument("--chip", default="esp32", help="esptool --chip 値")
    target_flash_esp32_parser.add_argument(
        "--no-verify",
        action="store_true",
        help="SHA256SUMS があっても checksum 検証を省略します",
    )
    target_flash_esp32_parser.add_argument(
        "--no-install-esptool",
        action="store_true",
        help="esptool 不在時に GAR 管理 venv へ自動導入しません",
    )
    target_flash_esp32_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="結果を機械可読な JSON で出力します（進捗は stderr / AI ・ CI 向け）",
    )

    usb_parser = subparsers.add_parser(
        "usb",
        help="USB-C 実機を usbipd-win 経由で WSL2 に attach します",
    )
    usb_subparsers = usb_parser.add_subparsers(dest="usb_command", metavar="command")
    for usb_command_name in ("attach", "detach", "status", "list", "bind"):
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
            usb_command_parser.add_argument(
                "--match",
                default=None,
                help="USB device description / VID:PID / BUSID の部分一致で対象を選びます（例: CH9102）",
            )
        if usb_command_name in ("status", "list"):
            usb_command_parser.add_argument(
                "--json",
                dest="json_output",
                action="store_true",
                help="結果を機械可読な JSON で出力します（AI / CI 向け）",
            )
        if usb_command_name in ("attach", "bind"):
            usb_command_parser.add_argument(
                "--no-remember",
                action="store_true",
                help="対象 busid を .gar/config.json に記憶しません",
            )

    hw_parser = subparsers.add_parser(
        "hw",
        help="hardware 定義 CSV を管理します",
    )
    hw_subparsers = hw_parser.add_subparsers(dest="hw_command", metavar="command")
    hw_init_parser = hw_subparsers.add_parser(
        "init",
        help="hardware 定義 CSV を gar-tools のテンプレートから作成します",
    )
    hw_init_parser.add_argument(
        "--dir",
        dest="output_dir",
        default=None,
        help="CSV を作成するディレクトリ（既定: ./hardware、テンプレート: gar-tools）",
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
        "shim": shim_parser,
        "sim": sim_parser,
        "sim_env": sim_env_parser,
        "sim_infra": sim_infra_parser,
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
        return run_setup(no_install=args.no_install, ec2_host=args.ec2_host, esp32_port=args.esp32_port, workspace_root=args.workspace_root)
    if args.command == "code":
        if args.code_command is None:
            subcommand_parsers["code"].print_help()
            return 1
        return run_code_command(
            CODE_COMMAND_MAP[args.code_command],
            codespace=getattr(args, "codespace", None),
            remote_path=getattr(args, "remote_path", None),
            mount_dir=getattr(args, "mount_dir", None),
            settings=getattr(args, "settings", None),
            profile_name=getattr(args, "profile_name", None),
            no_mount=getattr(args, "no_mount", False),
            shutdown=getattr(args, "shutdown", False),
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
    if args.command == "shim":
        if args.shim_command is None:
            subcommand_parsers["shim"].print_help()
            return 1
        return run_shim_command(
            args.shim_command,
            json_output=getattr(args, "json_output", False),
        )
    if args.command == "sim":
        if args.sim_command is None:
            subcommand_parsers["sim"].print_help()
            return 1
        if args.sim_command in SIM_VM_COMMAND_MAP:
            return run_sim_host_command(
                SIM_VM_COMMAND_MAP[args.sim_command],
                host=args.host,
                instance_id=args.instance_id,
                region=args.region,
                update_ssh=not getattr(args, "no_update_ssh", False),
                pull=getattr(args, "pull", False),
                json_output=getattr(args, "json_output", False),
            )
        if args.sim_command == "deploy":
            return run_sim_deploy_command(
                getattr(args, "artifacts_dir", None),
                host=getattr(args, "host", None),
                section="app",
            )
        if args.sim_command == "build":
            workspace_root = getattr(args, "workspace_root", None)
            clean = getattr(args, "action", None) == "clean"
            if workspace_root is None:
                return run_product_sim_build(clean=clean) if clean else run_product_sim_build()
            return run_product_sim_build(workspace_root=workspace_root, clean=clean) if clean else run_product_sim_build(workspace_root=workspace_root)
        if args.sim_command == "env":
            if args.sim_env_command is None:
                subcommand_parsers["sim_env"].print_help()
                return 1
            if args.sim_env_command == "build":
                workspace_root = getattr(args, "workspace_root", None)
                build_kwargs = {
                    "provider": getattr(args, "provider", None),
                    "json_output": getattr(args, "json_output", False),
                }
                if workspace_root is not None:
                    build_kwargs["workspace_root"] = workspace_root
                return run_sim_env_build_command(
                    **build_kwargs,
                )
            if args.sim_env_command == "deploy":
                return run_sim_deploy_command(
                    args.artifacts_dir,
                    host=args.host,
                    section="sim_env",
                )
            if args.sim_env_command == "gpio":
                if args.gpio_command is None:
                    subcommand_parsers["sim_env"].print_help()
                    return 1
                return run_sim_gpio_command(
                    args.gpio_command,
                    host=getattr(args, "host", None),
                    json_output=getattr(args, "json_output", False),
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
            return run_sim_infra_command(
                args.infra_command,
                key_name=getattr(args, "key_name", None),
                region=getattr(args, "region", None),
                auto_approve=getattr(args, "auto_approve", False),
            )
        subcommand_parsers["sim"].print_help()
        return 1
    if args.command == "target":
        if args.target_command is None:
            subcommand_parsers["target"].print_help()
            return 1
        if args.target_command == "deploy":
            return run_target_deploy_command(
                args.artifacts_dir,
                serial=args.serial,
                port=args.port,
                host=args.host,
                dest=args.dest,
                codespace=args.codespace,
                remote_root=args.remote_root,
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
        if args.target_command == "build":
            return run_target_build_command(
                codespace=args.codespace,
                remote_project_root=args.remote_project_root,
                pio_env=args.pio_env,
                local_artifact_root=args.artifact_root,
                flash=False,
                port=None,
                baud=921600,
                chip="esp32",
                verify=True,
                install_esptool=True,
            )
        if args.target_command == "build-esp32":
            return run_target_build_command(
                codespace=args.codespace,
                remote_project_root=args.remote_project_root,
                pio_env=args.pio_env,
                local_artifact_root=args.artifact_root,
                flash=args.flash,
                port=args.port,
                baud=args.baud,
                chip=args.chip,
                verify=not args.no_verify,
                install_esptool=not args.no_install_esptool,
            )
        if args.target_command == "flash-esp32":
            return _run_with_json_summary(
                "target flash-esp32",
                getattr(args, "json_output", False),
                lambda: run_target_flash_command(
                    artifact_dir=args.artifact_dir,
                    port=args.port,
                    baud=args.baud,
                    chip=args.chip,
                    verify=not args.no_verify,
                    install_esptool=not args.no_install_esptool,
                ),
            )

    if args.command == "usb":
        if args.usb_command is None:
            subcommand_parsers["usb"].print_help()
            return 1
        return run_usb_command(
            args.usb_command,
            busid=getattr(args, "busid", None),
            match=getattr(args, "match", None),
            remember=not getattr(args, "no_remember", False),
            json_output=getattr(args, "json_output", False),
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
