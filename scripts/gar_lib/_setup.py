"""`gar setup` subcommand: interactive provider selection + dependency check."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from scripts.gar_lib._config import (
    default_ec2_host,
    load_config,
    save_config,
    set_default_ec2_host,
)
from scripts.gar_lib._hw import load_hw_definition
from scripts.gar_lib._targets import (
    TargetManifest,
    discover_target_manifests,
    target_by_id,
)
from scripts.gar_lib._ui import (
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
from scripts.gar_lib._vscode import (
    install_vscode_terminal_bridge,
    installed_vscode_terminal_bridge_path,
)
from scripts.gar_lib.environments.base import DevEnvironment
from scripts.gar_lib.environments.discovery import discover_environment_providers
from scripts.gar_lib.environments.registry.simulation.wokwi import WokwiEnvironment
from scripts.gar_lib.sim.wokwi import WokwiSimProvider


def run_setup(no_install: bool = False, ec2_host: str | None = None) -> int:
    providers = discover_environment_providers()
    targets = discover_target_manifests()
    if not providers:
        print("接続環境プロバイダが見つかりません。", file=sys.stderr)
        return 1

    print(style("Gapless Agent Runtime の環境を設定します。", BOLD, CYAN))
    print(style("確認対象の状況を確認し、必要な項目を設定します。", DIM))
    print()
    config = load_config()
    config.setdefault("selected_providers", {})
    configure_target(config, targets, providers)
    print()
    print_terminal_bridge_status(offer_install=not no_install)
    print()
    configure_default_ec2_host(config, ec2_host=ec2_host)
    print()
    optional_categories = optional_setup_categories(config, targets)
    while True:
        categories = print_provider_overview(providers, config, optional_categories=optional_categories)
        category = select_setup_category(categories, config, optional_categories=optional_categories)
        if category is None:
            break

        provider = select_provider_for_category(category, config)
        if provider is None:
            break

        result = ensure_provider_dependencies(provider, no_install=no_install)
        if result == 0:
            config["selected_providers"][provider.category_id] = provider.provider_id
            save_config(config)
        else:
            break
        print()

    missing_categories = unconfigured_categories(providers, config, optional_categories=optional_categories)
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

    if optional_missing_categories:
        print(style("あとで設定できる項目:", BOLD, YELLOW))
        for category_name in optional_missing_categories:
            print(f"  - {style(category_name, YELLOW)}")

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


def configure_default_ec2_host(config: dict, *, ec2_host: str | None) -> None:
    selected_simulation = config.get("selected_providers", {}).get("simulation")
    if selected_simulation == "wokwi" and ec2_host is None:
        print(style("Simulation Runtime:", BOLD, BLUE))
        print(f"  {style('Wokwi はローカルCLIからクラウドシミュレーションを呼び出すため、SSH runtime host は不要です。', GREEN)}")
        return

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
        "gar sim の既定 runtime host を入力してください "
        f"[{current_host}]: ",
        default_on_eof=current_host,
    )
    selected_host = answer or current_host
    if selected_host != current_host:
        set_default_ec2_host(config, selected_host)
        save_config(config)
        print(f"  {style('更新しました:', GREEN)} {selected_host}")


def configure_target(
    config: dict,
    targets: Sequence[TargetManifest],
    providers: Sequence[type[DevEnvironment]],
) -> None:
    print(style("Target:", BOLD, BLUE))

    if not targets:
        print(f"  {style('target manifest が見つかりません。', YELLOW)}")
        print(f"     {style('gar-tools/targets/*/target.json を確認してください。', DIM)}")
        return

    configured_target_id = config.get("selected_target")
    selected = target_by_id(list(targets), configured_target_id)
    if selected is None:
        selected = targets[0]

    print_target_summary(selected, providers, indent="  ")

    if not sys.stdin.isatty():
        if configured_target_id is not None:
            ensure_selected_target_ready(config, selected)
        return

    if configured_target_id is not None:
        answer = safe_input("Target を変更しますか？ [y/N]: ", default_on_eof="n").lower()
        if answer not in ("y", "yes"):
            ensure_selected_target_ready(config, selected)
            return
    else:
        answer = safe_input("この Target を使いますか？ [Y/n]: ", default_on_eof="y").lower()
        if answer in ("", "y", "yes"):
            save_selected_target(config, selected)
            return
        if answer not in ("n", "no"):
            print(style("Target 一覧から選択します。", DIM))

    selected = select_target(targets, providers)
    if selected is None:
        return

    save_selected_target(config, selected)
    print(f"  {style('Target を保存しました:', GREEN)} {selected.display_name}")


def save_selected_target(config: dict, target: TargetManifest) -> None:
    config["selected_target"] = target.id
    apply_target_default_backends(config, target, overwrite=True)
    save_config(config)
    prepare_target_backend(target)


def ensure_selected_target_ready(config: dict, target: TargetManifest) -> None:
    before = dict(config.get("selected_providers", {}))
    apply_target_default_backends(config, target)
    if config.get("selected_providers", {}) != before:
        save_config(config)
    prepare_target_backend(target)


def apply_target_default_backends(config: dict, target: TargetManifest, *, overwrite: bool = False) -> None:
    selected_providers = config.setdefault("selected_providers", {})
    if overwrite:
        for category_id in managed_backend_categories():
            selected_providers.pop(category_id, None)
    for category_id, provider_id in target.default_backends.items():
        if category_id in selected_providers and not overwrite:
            continue
        selected_providers[category_id] = provider_id


def managed_backend_categories() -> set[str]:
    return {
        "development",
        "simulation",
        "device",
        "boot",
        "hostLink",
        "probe",
    }


def prepare_target_backend(target: TargetManifest) -> None:
    if target.default_backends.get("simulation") != "wokwi":
        return

    print()
    print(style("Wokwi project:", BOLD, BLUE))
    result = WokwiSimProvider(WokwiEnvironment, host=None).prepare_project(load_hw_definition())
    if result == 0:
        print(style("Wokwi プロジェクトを生成しました。", GREEN))


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
    print_target_backend_summary(target, providers, indent=indent)
    print_target_next_step_summary(target, indent=indent)


def print_target_backend_summary(
    target: TargetManifest,
    providers: Sequence[type[DevEnvironment]],
    *,
    indent: str = "     ",
) -> None:
    if not target.default_backends:
        return
    print(f"{indent}{style('このTargetで使う接続先:', BLUE)}")
    for category_id, provider_id in visible_target_backends(target).items():
        print(f"{indent}  - {backend_label(category_id)}: {provider_label(providers, provider_id)}")


def print_target_next_step_summary(target: TargetManifest, *, indent: str = "     ") -> None:
    if target.default_backends.get("simulation") != "wokwi":
        return
    print(f"{indent}{style('このsetupで行うこと:', BLUE)}")
    print(f"{indent}  Wokwi project + Wokwi CLI を準備します。")
    print(f"{indent}{style('任意の設定:', BLUE)}")
    print(f"{indent}  実機 ESP32 への書き込み設定は、このsetup内で続けて設定することも、後で追加することもできます。")


def backend_label(category_id: str) -> str:
    labels = {
        "development": "コードを書く/ビルドする場所",
        "simulation": "画面上で動かすシミュレータ",
        "device": "実機へ書き込む接続先",
    }
    return labels.get(category_id, category_id)


def visible_target_backends(target: TargetManifest) -> dict[str, str]:
    visible_categories = ("development", "simulation", "device")
    return {
        category_id: target.default_backends[category_id]
        for category_id in visible_categories
        if category_id in target.default_backends
    }


def provider_label(providers: Sequence[type[DevEnvironment]], provider_id: str) -> str:
    for provider in providers:
        if provider.provider_id == provider_id:
            return f"{provider.display_name} ({provider_id})"
    return provider_id


def selected_target_manifest(config: dict, targets: Sequence[TargetManifest]) -> TargetManifest | None:
    return target_by_id(list(targets), config.get("selected_target"))


def optional_setup_categories(config: dict, targets: Sequence[TargetManifest]) -> set[str]:
    target = selected_target_manifest(config, targets)
    if target is None:
        return set()
    if target.default_backends.get("simulation") == "wokwi":
        return {"device"}
    return set()


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
) -> list[tuple[str, str, list[type[DevEnvironment]]]]:
    print(style("確認対象の状況:", BOLD, BLUE))
    print()

    categories: list[tuple[str, str, list[type[DevEnvironment]]]] = []
    selected_providers = config["selected_providers"]
    optional_categories = optional_categories or set()

    for category_index, (_, category_name, grouped) in enumerate(
        grouped_providers(providers)
    ):
        category_number = len(categories) + 1
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
) -> tuple[str, str, list[type[DevEnvironment]]] | None:
    default_index = first_unconfigured_category_index(categories, config, optional_categories=optional_categories or set())
    if default_index is None:
        if optional_categories:
            prompt = "設定する項目番号を入力してください (Enter/qで終了、後で設定可の項目も番号で設定できます): "
        else:
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
