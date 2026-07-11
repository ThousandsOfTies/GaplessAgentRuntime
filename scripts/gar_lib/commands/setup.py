"""`gar setup` subcommand: interactive provider selection + dependency check."""

from __future__ import annotations

import shutil
import subprocess
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path

from scripts.gar_lib.config import (
    default_ec2_host,
    is_valid_runtime_host,
    load_config,
    save_config,
    saved_esp32_serial_port,
    saved_workspaces,
    set_active_workspace_root,
    set_default_ec2_host,
    set_saved_esp32_serial_port,
    set_saved_workspaces,
)
from scripts.gar_lib.environments.base import DevEnvironment
from scripts.gar_lib.environments.discovery import discover_environment_providers
from scripts.gar_lib.environments.registry.simulator.wokwi import WokwiEnvironment  # noqa: F401
from scripts.gar_lib.gar_tools import (
    TargetManifest,
    discover_target_manifests,
    ensure_gar_tools_available,
    target_by_id,
)
from scripts.gar_lib.simulation.wokwi import WokwiSimEnvProcessor  # noqa: F401
from scripts.gar_lib.vscode.terminal_bridge import (
    install_vscode_terminal_bridge,
    installed_vscode_terminal_bridge_path,
)
from scripts.gar_lib.vscode.terminal_ui import (
    BLUE,
    BOLD,
    CYAN,
    DIM,
    GREEN,
    RED,
    YELLOW,
    safe_input,
    style,
)

SKIP_CATEGORY = object()
TARGET_MENU_ENTRY = "__target_board__"


def run_setup(no_install: bool = False, ec2_host: str | None = None, esp32_port: str | None = None, workspace_root: str | None = None) -> int:
    providers = discover_environment_providers()
    if not providers:
        print("接続環境プロバイダが見つかりません。", file=sys.stderr)
        return 1

    print(style("Gapless Agent Runtime の環境を設定します。", BOLD, CYAN))
    print(style("確認対象の状況を確認し、必要な項目を設定します。", DIM))
    print()
    if not no_install:
        ensure_gar_tools_for_setup()
        print()
    targets = discover_target_manifests()
    config = load_config()
    config.setdefault("selected_providers", {})
    active_workspace_root: str | None = None
    if workspace_root or sys.stdin.isatty():
        active_workspace_root = configure_workspace_root(config, workspace_root=workspace_root)
        print()
    if active_workspace_root:
        set_active_workspace_root(active_workspace_root)
        config = load_config()
        config.setdefault("selected_providers", {})
    optional_categories = optional_setup_categories(config, targets)
    redraw_notice: str | None = None
    while True:
        if redraw_notice is None:
            print()
        else:
            clear_setup_screen()
            print(style(redraw_notice, GREEN))
            print()
            redraw_notice = None
        configure_target(config, targets, providers)
        print()
        categories = print_provider_overview(providers, config, optional_categories=optional_categories, start_index=2)
        category = select_setup_category(
            categories,
            config,
            optional_categories=optional_categories,
            start_index=2,
            target_configured=selected_target_manifest(config, targets) is not None,
        )
        if category is None:
            break
        if category[0] == TARGET_MENU_ENTRY:
            selected = select_target(targets, providers)
            if selected is None:
                break
            save_selected_target(config, selected)
            redraw_notice = f"更新しました: Target = {selected.display_name}"
            optional_categories = optional_setup_categories(config, targets)
            continue

        provider = select_provider_for_category(category, config)
        if provider is SKIP_CATEGORY:
            continue
        if provider is None:
            break

        result = ensure_provider_dependencies(provider, no_install=no_install)
        if result == 0:
            config["selected_providers"][provider.category_id] = provider.provider_id
            save_config(config)
            redraw_notice = f"更新しました: {category[1]} = {provider.display_name}"
        else:
            break

    missing_categories = []
    if targets and selected_target_manifest(config, targets) is None:
        missing_categories.append("Target")
    missing_categories.extend(unconfigured_categories(providers, config, optional_categories=optional_categories))
    optional_missing_categories = unconfigured_categories(providers, config, optional_categories=set(), only_categories=optional_categories)
    print()
    if missing_categories:
        print(style("未完了のセットアップ:", BOLD, RED))
        for category_name in missing_categories:
            print(f"  - {style(category_name, RED)}")
        if optional_missing_categories:
            print(style("あとで設定できる項目:", BOLD, YELLOW))
            for category_name in optional_missing_categories:
                print(f"  - {style(category_name, YELLOW)}")
        return 1

    selected_target = selected_target_manifest(config, targets)
    if selected_target is not None:
        prepare_target_backend(selected_target)
        print()

    print_terminal_bridge_status(offer_install=not no_install)
    print()
    configure_default_ec2_host(config, ec2_host=ec2_host)
    print()
    configure_esp32_serial_port(config, esp32_port=esp32_port)
    print()
    print_target_next_steps(config)
    print()

    if optional_missing_categories:
        print(style("あとで設定できる項目:", BOLD, YELLOW))
        for category_name in optional_missing_categories:
            print(f"  - {style(category_name, YELLOW)}")

    print(style("初期化が完了しました。", BOLD, GREEN))
    return 0


def ensure_gar_tools_for_setup() -> None:
    root = ensure_gar_tools_available(auto_clone=True)
    print(style("GAR Tools:", BOLD, BLUE))
    if root is None:
        print(f"  {style('未取得', YELLOW)}")
        print(f"     {style('gar-tools を .gar/tools に取得できませんでした。ネットワークまたは git を確認してください。', DIM)}")
        return
    print(f"  {style('利用可能', GREEN)} {style(str(root), DIM)}")


def clear_setup_screen() -> None:
    if not sys.stdout.isatty():
        return
    print("\033[2J\033[H", end="")


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


def configure_default_ec2_host(config: dict, *, ec2_host: str | None) -> None:
    selected_simulation = config.get("selected_providers", {}).get("simulator")
    if selected_simulation is None and ec2_host is None:
        return

    if selected_simulation != "ssh_remote" and ec2_host is None:
        print(style("Simulation Runtime:", BOLD, BLUE))
        print(f"  {style('選択中の simulation provider は SSH runtime host を必要としません。', GREEN)}")
        return

    current_host = default_ec2_host(config)

    if config.pop("_invalid_ec2_host", False):
        set_default_ec2_host(config, current_host)
        save_config(config)
        print(f"  {style('不正な既定 host を削除しました:', YELLOW)} {current_host}")

    if ec2_host:
        set_default_ec2_host(config, ec2_host)
        save_config(config)
        print(f"Runtime host: {style(ec2_host, BOLD, GREEN)}")
        return

    print(style("Simulation Runtime:", BOLD, BLUE))
    print(f"  既定 host: {style(current_host, BOLD)}")

    if not sys.stdin.isatty():
        return

    while True:
        answer = safe_input(
            "gar sim の既定 runtime host を入力してください "
            f"[{current_host}]: ",
            default_on_eof=current_host,
        )
        selected_host = answer or current_host
        if is_valid_runtime_host(selected_host):
            break
        print(f"  {style('host には制御文字や空白を含められません。SSH config の host 名または IP address を入力してください。', RED)}")
    if selected_host != current_host:
        set_default_ec2_host(config, selected_host)
        save_config(config)
        print(f"  {style('更新しました:', GREEN)} {selected_host}")


def configure_esp32_serial_port(config: dict, *, esp32_port: str | None = None) -> None:
    selected_target_provider = config.get("selected_providers", {}).get("target")
    selected_target = config.get("selected_target")
    if selected_target_provider != "esp32_esptool" or selected_target != "esp32":
        return

    current_port = saved_esp32_serial_port(config)
    candidates = detect_esp32_serial_port_candidates()
    default_port = current_port or (candidates[0] if len(candidates) == 1 else None)

    print(style("ESP32 Serial Port:", BOLD, BLUE))
    if esp32_port:
        set_saved_esp32_serial_port(config, esp32_port)
        save_config(config)
        print(f"  {style('更新しました:', GREEN)} {style(esp32_port, BOLD)}")
        return

    if current_port:
        print(f"  {style('設定済み', GREEN)} {style(current_port, BOLD)}")
    elif default_port:
        print(f"  {style('候補', YELLOW)} {style(default_port, BOLD)}")
    else:
        print(f"  {style('未設定', YELLOW)}")
        print(f"     {style('gar target deploy が使う serial port を setup で保存できます。', DIM)}")

    if candidates:
        print(f"     {style('検出候補:', DIM)} {', '.join(candidates)}")
    if not sys.stdin.isatty():
        if not current_port:
            print(f"     {style('保存するには対話 terminal で gar setup を実行するか、gar target deploy --port COM3 を使ってください。', DIM)}")
        return

    prompt_default = default_port or ""
    answer = safe_input(
        f"ESP32 serial port を入力してください"
        f"{f' [{prompt_default}]' if prompt_default else ' (例: COM3, /dev/ttyUSB0)'}: ",
        default_on_eof=prompt_default,
    ).strip()
    selected_port = answer or prompt_default
    if selected_port:
        set_saved_esp32_serial_port(config, selected_port)
        save_config(config)
        print(f"  {style('更新しました:', GREEN)} {selected_port}")


def configure_workspace_root(config: dict, *, workspace_root: str | None) -> str | None:
    workspaces = saved_workspaces(config)
    print(style("Product Workspaces:", BOLD, BLUE))
    if workspace_root:
        entry = prompt_workspace_entry("local", path_override=workspace_root)
        if entry is None:
            return None
        if workspace_duplicate(entry, workspaces):
            print(f"  {style('既に登録済みです:', YELLOW)} {entry['name']}")
        else:
            workspaces.append(entry)
            set_saved_workspaces(config, workspaces)
            save_config(config)
            print(f"  {style('追加しました:', GREEN)} {entry['name']}")
        return entry["id"]
    elif not sys.stdin.isatty():
        if workspaces:
            print(f"  {style('設定済み', GREEN)}")
            for entry in workspaces:
                print_workspace_entry(entry, indent="    - ")
        else:
            print(f"  {style('未設定', YELLOW)} --workspace-root または対話 setup で設定してください。")
        return workspaces[0]["id"] if len(workspaces) == 1 else None

    changed = False
    while True:
        if workspaces:
            print(f"  {style('設定済み:', GREEN)}")
            for index, entry in enumerate(workspaces, start=1):
                print_workspace_entry(entry, indent=f"    {index}. ")
        else:
            print(f"  {style('未設定', YELLOW)}")
        action = safe_input(
            "  workspaceを追加(a)、削除(d)、修正(e)、次へ(Enter): ",
            default_on_eof="",
        ).strip().lower()
        if not action:
            break
        if action in {"a", "add", "追加"}:
            entry = prompt_workspace_entry()
            if entry is None:
                continue
            if not workspace_duplicate(entry, workspaces):
                workspaces.append(entry)
                changed = True
                print(f"  {style('追加しました:', GREEN)} {entry['name']}")
            else:
                print(f"  {style('既に登録済みです:', YELLOW)} {entry['name']}")
            continue
        if action in {"d", "delete", "削除"}:
            if not workspaces:
                print(f"  {style('削除できる workspace がありません。', YELLOW)}")
                continue
            answer = safe_input("  削除する番号: ", default_on_eof="").strip()
            try:
                index = int(answer) - 1
                removed = workspaces.pop(index)
            except (ValueError, IndexError):
                print(f"  {style('番号が正しくありません。', RED)}")
                continue
            changed = True
            print(f"  {style('削除しました:', GREEN)} {removed['name']}")
            continue
        if action in {"e", "edit", "modify", "修正"}:
            if not workspaces:
                print(f"  {style('修正できる workspace がありません。', YELLOW)}")
                continue
            answer = safe_input("  修正する番号: ", default_on_eof="").strip()
            try:
                index = int(answer) - 1
                previous = workspaces[index]
            except (ValueError, IndexError):
                print(f"  {style('番号が正しくありません。', RED)}")
                continue
            entry = prompt_workspace_entry(existing=previous)
            if entry is None:
                continue
            other_entries = [candidate for candidate in workspaces if candidate["id"] != previous["id"]]
            if workspace_duplicate(entry, other_entries):
                print(f"  {style('既に登録済みです:', YELLOW)} {entry['name']}")
                continue
            workspaces[index] = entry
            changed = True
            print(f"  {style('修正しました:', GREEN)} {entry['name']}")
            continue
        print(f"  {style('a（追加）/ d（削除）/ e（修正）/ Enter（次へ）を入力してください。', YELLOW)}")

    if changed:
        set_saved_workspaces(config, workspaces)
        save_config(config)

    if not workspaces:
        return None
    active_id = config.get("workspace_id")
    if isinstance(active_id, str) and any(entry["id"] == active_id for entry in workspaces):
        return active_id
    if len(workspaces) == 1:
        return workspaces[0]["id"]
    while True:
        answer = safe_input("  設定する workspace の番号 [1]: ", default_on_eof="1").strip()
        if not answer:
            return workspaces[0]["id"]
        try:
            return workspaces[int(answer) - 1]["id"]
        except (ValueError, IndexError):
            print(f"  {style('番号が正しくありません。', RED)}")


def print_workspace_entry(entry: dict, *, indent: str) -> None:
    connection = entry["connection"]
    type_label = {"local": "local", "codespaces": "Codespaces", "network": "network"}[connection["type"]]
    location = connection["path"]
    if connection["type"] == "codespaces":
        location = f"{connection['codespace']}:{location}"
    elif connection["type"] == "network":
        location = f"{connection['host']}:{location}"
    print(f"{indent}{style(entry['name'], BOLD)} ({type_label} · {entry['branch']})")
    print(f"       {style(location, DIM)}")


def workspace_duplicate(candidate: dict, entries: Sequence[dict]) -> bool:
    connection = candidate["connection"]
    fingerprint = (
        connection["type"],
        connection.get("codespace") or connection.get("host") or "",
        connection["path"],
        candidate["branch"],
    )
    return any(
        (
            entry["connection"]["type"],
            entry["connection"].get("codespace") or entry["connection"].get("host") or "",
            entry["connection"]["path"],
            entry["branch"],
        )
        == fingerprint
        for entry in entries
    )


def prompt_workspace_entry(
    connection_type: str | None = None,
    *,
    existing: dict | None = None,
    path_override: str | None = None,
) -> dict | None:
    connection = existing.get("connection", {}) if existing else {}
    selected_type = connection_type or connection.get("type")
    if selected_type is None:
        print("  接続種別を選択してください:")
        print("    1. Codespaces")
        print("    2. Local")
        print("    3. Network (SSH)")
        selected = safe_input("  番号 [2]: ", default_on_eof="").strip() or "2"
        selected_type = {"1": "codespaces", "2": "local", "3": "network"}.get(selected)
        if selected_type is None:
            print(f"  {style('番号が正しくありません。', RED)}")
            return None

    if selected_type == "local":
        default_path = path_override or connection.get("path", "")
        answer = path_override or safe_input(
            f"  local path{f' [{default_path}]' if default_path else ''}: ",
            default_on_eof=default_path,
        ).strip()
        if not answer:
            return None
        path = Path(answer).expanduser().resolve()
        if not path.is_dir():
            print(f"  {style('存在しない directory です:', RED)} {path}")
            return None
        workspace_connection = {"type": "local", "path": str(path)}
        repo_name, branch = probe_git_workspace(["git", "-C", str(path)])
    elif selected_type == "codespaces":
        print_codespace_candidates()
        default_codespace = connection.get("codespace", "")
        codespace = safe_input(
            f"  Codespace名{f' [{default_codespace}]' if default_codespace else ''}: ",
            default_on_eof=default_codespace,
        ).strip() or default_codespace
        if not codespace:
            return None
        default_path = connection.get("path", "/workspaces/gar-build-env")
        path = safe_input(f"  Codespace内の path [{default_path}]: ", default_on_eof=default_path).strip() or default_path
        workspace_connection = {"type": "codespaces", "codespace": codespace, "path": path}
        repo_name, branch = probe_git_workspace(["gh", "codespace", "ssh", "-c", codespace, "--", "git", "-C", path])
    else:
        default_host = connection.get("host", "")
        host = safe_input(
            f"  IP address または SSH host{f' [{default_host}]' if default_host else ''}: ",
            default_on_eof=default_host,
        ).strip() or default_host
        if not host:
            return None
        default_path = connection.get("path", "")
        path = safe_input(
            f"  remote path{f' [{default_path}]' if default_path else ''}: ",
            default_on_eof=default_path,
        ).strip() or default_path
        if not path:
            return None
        workspace_connection = {"type": "network", "host": host, "path": path}
        repo_name, branch = probe_git_workspace(["ssh", host, "git", "-C", path])

    if not branch:
        branch = safe_input("  branch [main]: ", default_on_eof="main").strip() or "main"
    if not repo_name:
        repo_name = Path(workspace_connection["path"]).name or "workspace"
    default_name = f"{repo_name} · {branch}"
    name = safe_input(f"  表示名 [{default_name}]: ", default_on_eof=default_name).strip() or default_name
    return {
        "id": existing["id"] if existing else f"ws_{uuid.uuid4().hex}",
        "name": name,
        "connection": workspace_connection,
        "branch": branch,
    }


def print_codespace_candidates() -> None:
    if shutil.which("gh") is None:
        return
    result = subprocess.run(["gh", "codespace", "list"], check=False, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        print(f"  {style('利用可能な Codespaces:', DIM)}")
        for line in result.stdout.splitlines():
            print(f"    {line}")


def probe_git_workspace(command_prefix: list[str]) -> tuple[str | None, str | None]:
    try:
        branch_result = subprocess.run(
            [*command_prefix, "rev-parse", "--abbrev-ref", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
        repo_result = subprocess.run(
            [*command_prefix, "config", "--get", "remote.origin.url"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None, None
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
    remote = repo_result.stdout.strip() if repo_result.returncode == 0 else ""
    repo_name = Path(remote.removesuffix(".git")).name if remote else None
    return repo_name, branch


def detect_esp32_serial_port_candidates() -> list[str]:
    patterns = ("/dev/ttyACM*", "/dev/ttyUSB*", "/dev/ttyS*")
    candidates: list[str] = []
    for pattern in patterns:
        for path in sorted(Path("/").glob(pattern.removeprefix("/"))):
            if path.exists():
                candidates.append(str(path))
    return candidates


def print_target_next_steps(config: dict) -> None:
    selected_simulation = config.get("selected_providers", {}).get("simulator")
    if selected_simulation != "wokwi":
        return

    print(style("次の操作フェーズ:", BOLD, BLUE))
    print(f"  {style('1. Wokwi firmware/shim をビルド:', BOLD)}")
    print("    scripts/gar sim env build")
    print(f"     {style('このtargetのWokwi build入口です。workspace生成後、内部で m5stickc-client の make wokwi-build を実行します。', DIM)}")
    print(f"     {style('workspace生成だけをしたい場合: cd ../gar-vibe-ui/vibe-remote/m5stickc-client && make wokwi-workspace', DIM)}")
    print(f"  {style('2. Wokwi simulation を起動:', BOLD)}")
    print("    PATH=\"$HOME/bin:$HOME/.venvs/platformio/bin:$PATH\" scripts/gar sim env start --no-port-forward")
    print(f"  {style('3. 人間がUIを確認:', BOLD)}")
    print("    code .gar/wokwi/m5stackc")
    print(f"     {style('VS Codeで diagram.json を開き、Wokwi の再生ボタンで確認します。', DIM)}")
    print(f"     {style('AIはこのフェーズ表を見て、未定義のgarコマンドではなく現在の実装済み入口を選びます。', DIM)}")


def configure_target(
    config: dict,
    targets: Sequence[TargetManifest],
    providers: Sequence[type[DevEnvironment]],
) -> None:
    print(style("1. Target", BOLD, CYAN))

    if not targets:
        print(f"  {style('未設定', BOLD, YELLOW)}")
        print(f"     {style('gar-tools/targets/*/target.json を確認してください。', DIM)}")
        return

    configured_target_id = config.get("selected_target")
    selected = target_by_id(list(targets), configured_target_id)
    target_configured = selected is not None
    if selected is None:
        selected = targets[0]

    print_selected_target_summary(selected, configured=target_configured)

    if target_configured:
        ensure_selected_target_ready(config, selected)


def save_selected_target(config: dict, target: TargetManifest) -> None:
    config["selected_target"] = target.id
    for category_id in managed_backend_categories():
        config.setdefault("selected_providers", {}).pop(category_id, None)
    save_config(config)


def ensure_selected_target_ready(config: dict, target: TargetManifest) -> None:
    before = dict(config.get("selected_providers", {}))
    prune_removed_target_backends(config, target)
    if config.get("selected_providers", {}) != before:
        save_config(config)


def prune_removed_target_backends(config: dict, target: TargetManifest) -> None:
    selected_providers = config.setdefault("selected_providers", {})
    for category_id in removable_target_backend_categories() - set(target.default_backends):
        selected_providers.pop(category_id, None)


def removable_target_backend_categories() -> set[str]:
    return {
        "boot",
        "hostLink",
        "probe",
    }


def managed_backend_categories() -> set[str]:
    return {
        "codespace",
        "simulator",
        "target",
        "boot",
        "hostLink",
        "probe",
    }


def prepare_target_backend(target: TargetManifest) -> None:
    if target.default_backends.get("simulator") != "wokwi":
        return

    print()
    print(style("Wokwi project:", BOLD, BLUE))
    print(f"  {style('製品 workspace の scripts/product-sim-build.sh が gar sim build 実行時に生成します。', DIM)}")


def select_target(
    targets: Sequence[TargetManifest],
    providers: Sequence[type[DevEnvironment]],
) -> TargetManifest | None:
    print()
    print(style("[Target]", BOLD, CYAN))
    print(style("確認したい実行面を選択してください:", BOLD))
    print()
    for index, target in enumerate(targets, start=1):
        print(f"  {style(str(index) + '.', BOLD)} {style(target.display_name, BOLD)}")
        print_target_summary(target, providers, indent="     ", include_name=False)
        print()

    selected_index = _select_target_index(len(targets))
    if selected_index is None:
        return None
    return targets[selected_index - 1]


def print_target_summary(
    target: TargetManifest,
    providers: Sequence[type[DevEnvironment]],
    *,
    indent: str,
    include_name: bool = True,
) -> None:
    if include_name:
        print(f"{indent}{style('Selected:', BLUE)}")
        print(
            f"{indent}  {style(target.display_name, BOLD)} "
            f"{style(f'({target.id})', DIM)}"
        )
    print(f"{indent}{style('Description:', BLUE)}")
    print(f"{indent}  {style(target.description, DIM)}")


def print_selected_target_summary(target: TargetManifest, *, configured: bool) -> None:
    if not configured:
        print(f"  {style('未設定', BOLD, YELLOW)}")
        print(f"     {style('この項目を選ぶとTargetを選択できます。', DIM)}")
        return

    print(
        f"  {style('設定済み', BOLD, GREEN)} "
        f"{style(target.display_name, BOLD)} "
        f"{style(f'({target.id})', DIM)}"
    )
    print(f"     {style(target.description, DIM)}")


def selected_target_manifest(config: dict, targets: Sequence[TargetManifest]) -> TargetManifest | None:
    return target_by_id(list(targets), config.get("selected_target"))


def optional_setup_categories(config: dict, targets: Sequence[TargetManifest]) -> set[str]:
    target = selected_target_manifest(config, targets)
    if target is None:
        return set()
    optional = {"simulator"}
    if target.default_backends.get("simulator") == "wokwi":
        optional.add("target")
    return optional


def _select_target_index(count: int) -> int | None:
    while True:
        raw = safe_input("番号を入力してください [1]: ")
        if raw == "":
            return 1
        if raw.lower() in ("q", "quit", "exit"):
            return None

        try:
            selected_index = int(raw)
        except ValueError:
            print(style("番号で入力してください。", YELLOW))
            continue

        if 1 <= selected_index <= count:
            return selected_index

        print(style(f"1 から {count} の番号を入力してください。", YELLOW))


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
        print(style(f"{provider.display_name} に必要なコマンドは見つかりました。", GREEN))
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
        print(style(f"{provider.display_name} に必要なコマンドは見つかりました。", GREEN))
        return 0

    print(provider.install_hint(missing))
    return 1


def print_provider_overview(
    providers: Sequence[type[DevEnvironment]],
    config: dict[str, dict[str, str]],
    *,
    optional_categories: set[str] | None = None,
    start_index: int = 1,
) -> list[tuple[str, str, list[type[DevEnvironment]]]]:
    categories: list[tuple[str, str, list[type[DevEnvironment]]]] = []
    selected_providers = config["selected_providers"]
    optional_categories = optional_categories or set()

    for category_index, (_, category_name, grouped) in enumerate(grouped_providers(providers)):
        category_number = start_index + len(categories)
        categories.append((grouped[0].category_id, category_name, grouped))
        if category_index > 0:
            print()

        optional_text = f" {style('(後で設定可)', YELLOW)}" if grouped[0].category_id in optional_categories else ""
        print(style(f"{category_number}. {category_name}", BOLD, CYAN) + optional_text)

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
    *,
    optional_categories: set[str] | None = None,
    start_index: int = 1,
    target_configured: bool = True,
) -> tuple[str, str, list[type[DevEnvironment]]] | None:
    default_index = None if not target_configured else first_unconfigured_category_index(categories, config, optional_categories=optional_categories or set())
    if default_index is None:
        if not target_configured:
            prompt = "設定する項目番号を入力してください [1: Target] (qで終了): "
        elif optional_categories:
            prompt = "設定する項目番号を入力してください (Enter/qで終了、後で設定可の項目も番号で設定できます): "
        else:
            prompt = "設定する項目番号を入力してください (Enter/qで終了): "
    else:
        default_category = categories[default_index - 1]
        default_number = start_index + default_index - 1
        prompt = (
            "設定する項目番号を入力してください "
            f"[{default_number}: {default_category[1]}] "
            "(qで終了): "
        )

    while True:
        raw = safe_input(prompt)
        if raw == "":
            if not target_configured:
                return (TARGET_MENU_ENTRY, "Target", [])
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

        if selected == 1:
            return (TARGET_MENU_ENTRY, "Target", [])

        list_index = selected - start_index
        if 0 <= list_index < len(categories):
            return categories[list_index]

        last_index = start_index + len(categories) - 1
        print(style(f"1 または {start_index} から {last_index} の番号を入力してください。", YELLOW))


def select_provider_for_category(
    category: tuple[str, str, list[type[DevEnvironment]]],
    config: dict[str, dict[str, str]],
) -> type[DevEnvironment] | None | object:
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
            return SKIP_CATEGORY

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
        if raw.lower() in ("q", "quit", "exit"):
            return None

        try:
            selected_index = int(raw)
        except ValueError:
            print(style("番号で入力してください。", YELLOW))
            continue

        if 1 <= selected_index <= len(providers):
            return providers[selected_index - 1]

        print(style(f"1 から {len(providers)} の番号を入力してください。", YELLOW))


def unconfigured_categories(
    providers: Sequence[type[DevEnvironment]],
    config: dict[str, dict[str, str]],
    *,
    optional_categories: set[str] | None = None,
    only_categories: set[str] | None = None,
) -> list[str]:
    missing: list[str] = []
    selected_providers = config["selected_providers"]
    optional_categories = optional_categories or set()

    for category_id, category_name, grouped in grouped_providers(providers):
        if only_categories is not None and category_id not in only_categories:
            continue
        if category_id in optional_categories:
            continue
        selected = provider_by_id(grouped, selected_providers.get(category_id))
        if selected is None or selected.missing_commands():
            missing.append(category_name)

    return missing


def first_unconfigured_category_index(
    categories: Sequence[tuple[str, str, list[type[DevEnvironment]]]],
    config: dict[str, dict[str, str]],
    *,
    optional_categories: set[str] | None = None,
) -> int | None:
    selected_providers = config["selected_providers"]
    optional_categories = optional_categories or set()

    for index, (category_id, _, providers) in enumerate(categories, start=1):
        if category_id in optional_categories:
            continue
        selected = provider_by_id(providers, selected_providers.get(category_id))
        if selected is None or selected.missing_commands():
            return index

    for index, (category_id, _, providers) in enumerate(categories, start=1):
        if category_id not in optional_categories:
            continue
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
