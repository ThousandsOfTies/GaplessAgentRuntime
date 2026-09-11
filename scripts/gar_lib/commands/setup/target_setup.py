"""Target selection and target-specific connection phases for ``gar config``."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from scripts.gar_lib.access.serial import serial_port_candidates
from scripts.gar_lib.core.config import (
    save_config,
    saved_esp32_serial_port,
    saved_target_setting,
    set_saved_esp32_serial_port,
    set_saved_target_setting,
)
from scripts.gar_lib.target.manifest import TargetManifest, target_by_id
from scripts.gar_lib.vscode.terminal_ui import (
    BLUE,
    BOLD,
    CYAN,
    DIM,
    GREEN,
    YELLOW,
    safe_input,
    style,
)


def configure_target(config: dict, targets: Sequence[TargetManifest]) -> None:
    """Print target status and remove settings no longer valid for that target."""

    print(style("1. Target", BOLD, CYAN))
    if not targets:
        print(f"  {style('未設定', BOLD, YELLOW)}")
        print(f"     {style('gar-tools/targets/*/target.json を確認してください。', DIM)}")
        return

    selected = selected_target_manifest(config, targets)
    target_configured = selected is not None
    if selected is None:
        selected = targets[0]
    print_selected_target_summary(selected, configured=target_configured)

    if target_configured:
        ensure_selected_target_ready(config, selected)


def save_selected_target(config: dict, target: TargetManifest) -> None:
    config["selected_target"] = target.id
    selected_environments = config.setdefault("selected_environments", {})
    for category_id in managed_backend_categories():
        selected_environments.pop(category_id, None)
    save_config(config)


def ensure_selected_target_ready(config: dict, target: TargetManifest) -> None:
    before = dict(config.get("selected_environments", {}))
    prune_removed_target_backends(config, target)
    if config.get("selected_environments", {}) != before:
        save_config(config)


def prune_removed_target_backends(config: dict, target: TargetManifest) -> None:
    selected_environments = config.setdefault("selected_environments", {})
    removed_categories = removable_target_backend_categories() - set(target.default_backends)
    for category_id in removed_categories:
        selected_environments.pop(category_id, None)


def removable_target_backend_categories() -> set[str]:
    return {"boot", "hostLink", "probe"}


def managed_backend_categories() -> set[str]:
    return {
        "codespace",
        "simulator",
        "simulation_host",
        "target",
        "boot",
        "hostLink",
        "probe",
    }


def prepare_target_backend(target: TargetManifest) -> None:
    if target.default_backends.get("simulator") != "wokwi":
        return

    print()
    print(style("Wokwi build:", BOLD, BLUE))
    build_hook_message = (
        "製品 workspace の scripts/product-sim-build.sh が "
        "gar sim build app 実行時にfirmwareとartifactを生成します。"
    )
    print(f"  {style(build_hook_message, DIM)}")


def select_target(targets: Sequence[TargetManifest]) -> TargetManifest | None:
    print()
    print(style("[Target]", BOLD, CYAN))
    print(style("確認したい実行面を選択してください:", BOLD))
    print()
    for index, target in enumerate(targets, start=1):
        print(f"  {style(str(index) + '.', BOLD)} {style(target.display_name, BOLD)}")
        print_target_summary(target, indent="     ", include_name=False)
        print()

    selected_index = _select_target_index(len(targets))
    if selected_index is None:
        return None
    return targets[selected_index - 1]


def print_target_summary(
    target: TargetManifest,
    *,
    indent: str,
    include_name: bool = True,
) -> None:
    if include_name:
        print(f"{indent}{style('Selected:', BLUE)}")
        print(f"{indent}  {style(target.display_name, BOLD)} " f"{style(f'({target.id})', DIM)}")
    print(f"{indent}{style('Description:', BLUE)}")
    print(f"{indent}  {style(target.description, DIM)}")


def print_selected_target_summary(target: TargetManifest, *, configured: bool) -> None:
    if not configured:
        print(f"  {style('未設定', BOLD, YELLOW)}")
        print(f"     {style('この項目を選ぶとTargetを選択できます。', DIM)}")
        return

    print(
        f"  {style('設定済み', BOLD, GREEN)} " f"{style(target.display_name, BOLD)} " f"{style(f'({target.id})', DIM)}"
    )
    print(f"     {style(target.description, DIM)}")


def selected_target_manifest(
    config: dict,
    targets: Sequence[TargetManifest],
) -> TargetManifest | None:
    target_id = config.get("selected_target")
    return target_by_id(list(targets), target_id if isinstance(target_id, str) else None)


def optional_setup_categories(config: dict, targets: Sequence[TargetManifest]) -> set[str]:
    target = selected_target_manifest(config, targets)
    if target is None:
        return set()
    optional = {"simulator"}
    if config.get("selected_environments", {}).get("simulator") != "ssh_remote":
        optional.add("simulation_host")
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


def configure_esp32_serial_port(config: dict, *, esp32_port: str | None = None) -> None:
    selected_target_environment = config.get("selected_environments", {}).get("target")
    selected_target = config.get("selected_target")
    if selected_target_environment != "esp32_esptool" or selected_target != "esp32":
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
        serial_port_message = "gar target deploy が使う serial port をworkspace設定へ保存できます。"
        print(f"     {style(serial_port_message, DIM)}")

    if candidates:
        print(f"     {style('検出候補:', DIM)} {', '.join(candidates)}")
    if not sys.stdin.isatty():
        if not current_port:
            print(f"     {style('保存するには対話 terminal で gar config を実行してください。', DIM)}")
        return

    prompt_default = default_port or ""
    prompt_example = f" [{prompt_default}]" if prompt_default else " (例: COM3, /dev/ttyUSB0)"
    answer = safe_input(
        f"ESP32 serial port を入力してください{prompt_example}: ",
        default_on_eof=prompt_default,
    ).strip()
    selected_port = answer or prompt_default
    if selected_port:
        set_saved_esp32_serial_port(config, selected_port)
        save_config(config)
        print(f"  {style('更新しました:', GREEN)} {selected_port}")


def configure_target_connection(config: dict) -> None:
    environment_id = config.get("selected_environments", {}).get("target")
    if environment_id not in {"adb_usb", "adb_win", "ssh_scp", "uuu"}:
        return

    print(style("Target Runtime:", BOLD, BLUE))
    if environment_id == "ssh_scp":
        _configure_ssh_target(config)
    elif environment_id == "uuu":
        _configure_uuu_target(config)
    else:
        _configure_adb_target(config)


def _configure_ssh_target(config: dict) -> None:
    current = saved_target_setting(config, "host")
    print("  SSH config の Host 名で接続します（鍵なども同じ設定を使用します）。")
    if current:
        print(f"  現在の SSH Host: {style(current, BOLD, GREEN)}")
    else:
        print(f"  現在の SSH Host: {style('未設定', YELLOW)}")
    if not sys.stdin.isatty():
        if not current:
            print(f"     {style('対話terminalでgar configを実行して実機のSSH hostを保存してください。', DIM)}")
        return

    answer = safe_input(
        f"  SSH Host 名 [{current or '入力必須'}]: ",
        default_on_eof=current or "",
    ).strip()
    selected = answer or current
    if selected and selected != current:
        set_saved_target_setting(config, "host", selected)
        save_config(config)
        print(f"  {style('更新しました:', GREEN)} {selected}")


def _configure_adb_target(config: dict) -> None:
    current = saved_target_setting(config, "serial")
    print(f"  ADB device: {style(current or '既定デバイス', BOLD, GREEN)}")
    if not sys.stdin.isatty():
        return
    answer = safe_input(
        "ADB device serial を入力してください" f"{f' [{current}]' if current else ' (未入力なら既定デバイス)'}: ",
        default_on_eof=current or "",
    ).strip()
    if answer and answer != current:
        set_saved_target_setting(config, "serial", answer)
        save_config(config)
        print(f"  {style('更新しました:', GREEN)} {answer}")


def _configure_uuu_target(config: dict) -> None:
    current = saved_target_setting(config, "serial")
    candidates = detect_uuu_serial_port_candidates()
    default_port = current or (candidates[0] if len(candidates) == 1 else None)
    print("  USB-C debug UART: " f"{style(current or default_port or '未設定', BOLD, GREEN)}")
    print("  UUUのdownload USBと、起動確認用のUSB-C debug UARTは別接続です。")
    if candidates:
        print(f"     {style('検出候補:', DIM)} {', '.join(candidates)}")
    if not sys.stdin.isatty():
        if not current:
            print(f"     {style('保存するには対話 terminal でgar configを実行してください。', DIM)}")
        return
    prompt_default = default_port or ""
    prompt_example = f" [{prompt_default}]" if prompt_default else " (例: /dev/ttyCH343USB0)"
    answer = safe_input(
        f"USB-C debug UART deviceを入力してください{prompt_example}: ",
        default_on_eof=prompt_default,
    ).strip()
    selected = answer or prompt_default
    if selected and selected != current:
        set_saved_target_setting(config, "serial", selected)
        save_config(config)
        print(f"  {style('更新しました:', GREEN)} {selected}")


def detect_esp32_serial_port_candidates() -> list[str]:
    detected = serial_port_candidates()
    if detected:
        return detected
    patterns = ("/dev/ttyACM*", "/dev/ttyUSB*", "/dev/ttyS*")
    candidates: list[str] = []
    for pattern in patterns:
        for path in sorted(Path("/").glob(pattern.removeprefix("/"))):
            if path.exists():
                candidates.append(str(path))
    return candidates


def detect_uuu_serial_port_candidates() -> list[str]:
    detected = serial_port_candidates()
    if detected:
        return detected
    patterns = ("/dev/ttyCH343USB*", "/dev/ttyCH342USB*", "/dev/ttyUSB*", "/dev/ttyACM*")
    candidates: list[str] = []
    for pattern in patterns:
        for path in sorted(Path("/").glob(pattern.removeprefix("/"))):
            if path.exists():
                candidates.append(str(path))
    return candidates


def print_target_next_steps(config: dict) -> None:
    selected_simulation = config.get("selected_environments", {}).get("simulator")
    if selected_simulation != "wokwi":
        return

    print(style("次の操作フェーズ:", BOLD, BLUE))
    print(f"  {style('1. 製品の Wokwi firmware をビルド:', BOLD)}")
    print("    scripts/gar sim build app")
    firmware_build_message = (
        "製品 workspace の product-sim-build hook が firmware をビルドし、実行用 artifact を作成します。"
    )
    print(f"     {style(firmware_build_message, DIM)}")
    print(f"  {style('2. Wokwi project を配置:', BOLD)}")
    print("    scripts/gar sim deploy app")
    print(f"     {style('artifact を選択中の runtime workspace に展開します。', DIM)}")
    print(f"  {style('3. Wokwi simulation を起動:', BOLD)}")
    print('    PATH="$HOME/bin:$HOME/.venvs/platformio/bin:$PATH" ' "scripts/gar sim start --no-port-forward")
    print(f"  {style('4. 人間がUIを確認:', BOLD)}")
    print("    scripts/gar sim diag --json  # project_dir を確認")
    print("    code /path/from/project_dir")
    print(f"     {style('VS Codeで diagram.json を開き、Wokwi の再生ボタンで確認します。', DIM)}")
    phase_guidance_message = "AIはこのフェーズ表を見て、未定義のgarコマンドではなく現在の実装済み入口を選びます。"
    print(f"     {style(phase_guidance_message, DIM)}")
