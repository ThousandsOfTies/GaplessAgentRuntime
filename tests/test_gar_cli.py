from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from scripts.gar_lib.access.ssh_config import SshConfigHostAddressUpdater
from scripts.gar_lib.artifacts.manifest import fetch_codespace_artifacts
from scripts.gar_lib.cli import (
    completion_bash_script,
    main,
    normalize_question_help,
)
from scripts.gar_lib.commands.code import (
    run_code_command,
    shutdown_code_codespace,
    start_code_codespace,
    stop_code_codespace,
)
from scripts.gar_lib.commands.infra import run_sim_infra_command
from scripts.gar_lib.commands.setup import run_setup
from scripts.gar_lib.commands.terminal import run_terminal_request
from scripts.gar_lib.commands.usb import parse_usbipd_list, run_usb_command
from scripts.gar_lib.config import load_config
from scripts.gar_lib.core.command import (
    SIM_BUILD,
    SIM_CLEAN,
    SIM_HOST_START,
    SIM_HOST_STATUS,
    SIM_HOST_STOP,
    SIM_RUNTIME_BUILD,
    SIM_RUNTIME_DEPLOY,
    SIM_RUNTIME_DIAG,
    SIM_RUNTIME_START,
    TARGET_BUILD,
    TARGET_DEPLOY,
    GarCommand,
)
from scripts.gar_lib.environments.base import EnvironmentSetupOption
from scripts.gar_lib.gar_tools import TargetManifest, discover_target_manifests, ensure_gar_tools_available
from scripts.gar_lib.simulation.linux import LinuxSystemdCommandBuilder, gpio_sim_plan
from scripts.gar_lib.simulation.parse import parse_gpio_runtime_status, parse_gpio_sim_check, parse_sim_diag
from scripts.gar_lib.target.esptool import normalize_esp32_serial_port, run_esp32_flash_command
from scripts.gar_lib.targets.esp32 import parse_esp32_build_artifact_path, run_esp32_build_command


class DevelopmentProvider(EnvironmentSetupOption):
    provider_id = "development_test"
    display_name = "Development Test"
    description = "codespace"
    category_id = "codespace"
    category_name = "開発環境"
    required_commands = ()


class SimulationProvider(EnvironmentSetupOption):
    provider_id = "simulation_test"
    display_name = "Simulation Test"
    description = "simulator"
    category_id = "simulator"
    category_name = "シミュレート環境"
    required_commands = ()


class WokwiProvider(EnvironmentSetupOption):
    provider_id = "wokwi"
    display_name = "Wokwi"
    description = "wokwi"
    category_id = "simulator"
    category_name = "シミュレート環境"
    required_commands = ()


class MissingSimulationProvider(EnvironmentSetupOption):
    provider_id = "missing_simulation"
    display_name = "Missing Simulation"
    description = "missing simulation"
    category_id = "simulator"
    category_name = "シミュレート環境"
    required_commands = ("missing-sim-command",)


class TargetAccessProvider(EnvironmentSetupOption):
    provider_id = "device_test"
    display_name = "Device Test"
    description = "target"
    category_id = "target"
    category_name = "実機環境"
    required_commands = ()


class MissingTargetAccessProvider(EnvironmentSetupOption):
    provider_id = "missing_test"
    display_name = "Missing Test"
    description = "missing"
    category_id = "target"
    category_name = "実機環境"
    required_commands = ("missing-command",)


class GarCliTest(unittest.TestCase):
    def test_question_mark_prints_contextual_help(self) -> None:
        cases = [
            (["?"], "usage: gar", "code"),
            (["code", "?"], "usage: gar code", "start"),
            (["sim", "env", "gpio", "?"], "usage: gar sim env gpio", "plan"),
        ]

        for argv, usage, command in cases:
            with self.subTest(argv=argv):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = main(argv)

                self.assertEqual(0, result)
                text = output.getvalue()
                self.assertIn(usage, text)
                self.assertIn(command, text)

    def test_question_mark_normalization_ignores_command_remainder(self) -> None:
        self.assertEqual(["code", "--help"], normalize_question_help(["code", "?"]))
        self.assertEqual(
            ["terminal", "run", "--", "echo", "?"],
            normalize_question_help(["terminal", "run", "--", "echo", "?"]),
        )

    def test_completion_bash_script_uses_argcomplete(self) -> None:
        text = completion_bash_script()
        self.assertIn("register-python-argcomplete gar", text)
        self.assertIn("eval", text)
        self.assertIn("completion words", text)

    def test_completion_bash_is_available_from_cli(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["completion", "bash"])

        self.assertEqual(0, result)
        self.assertIn("register-python-argcomplete gar", output.getvalue())

    def test_completion_words_uses_parser_commands(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["completion", "words", "--cword", "2", "--", "gar", "sim", ""])

        self.assertEqual(0, result)
        self.assertIn("env", output.getvalue().splitlines())
        self.assertIn("start", output.getvalue().splitlines())
        self.assertIn("stop", output.getvalue().splitlines())
        self.assertNotIn("ui", output.getvalue().splitlines())

    def test_setup_lists_only_selected_provider_for_configured_category(self) -> None:
        providers = [DevelopmentProvider, SimulationProvider, TargetAccessProvider]
        targets = [
            TargetManifest(
                id="test-target",
                display_name="Test Target",
                description="target",
                tools_root="targets/test",
                default_backends={
                    "codespace": "development_test",
                    "simulator": "simulation_test",
                    "target": "device_test",
                },
                backend_notes={},
            ),
        ]
        config = {
            "selected_target": "test-target",
            "selected_providers": {
                "codespace": "development_test",
                "simulator": "simulation_test",
                "target": "device_test",
            }
        }

        with (
            mock.patch("scripts.gar_lib.commands.setup.discover_environment_providers", return_value=providers),
            mock.patch("scripts.gar_lib.commands.setup.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("builtins.input", return_value=""),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_setup(no_install=True)

        self.assertEqual(0, result)
        text = output.getvalue()
        self.assertIn("1. Target", text)
        self.assertIn("2. 開発環境", text)
        self.assertIn("3. シミュレート環境", text)
        self.assertIn("4. 実機環境", text)
        self.assertLess(text.index("1. Target"), text.index("2. 開発環境"))
        self.assertLess(text.index("2. 開発環境"), text.index("VSCode Terminal Bridge:"))
        self.assertIn("VSCode Terminal Bridge:", text)
        self.assertIn("未導入", text)
        self.assertIn("設定済み", text)
        self.assertNotIn("1. Development Test", text)
        self.assertIn("初期化が完了しました。", text)

    def test_setup_defaults_to_first_unconfigured_category_provider(self) -> None:
        providers = [DevelopmentProvider, MissingTargetAccessProvider]
        targets = [
            TargetManifest(
                id="test-target",
                display_name="Test Target",
                description="target",
                tools_root="targets/test",
                default_backends={
                    "codespace": "development_test",
                    "target": "missing_test",
                },
                backend_notes={},
            ),
        ]
        config = {
            "selected_target": "test-target",
            "selected_providers": {"codespace": "development_test"},
        }

        with (
            mock.patch("scripts.gar_lib.commands.setup.discover_environment_providers", return_value=providers),
            mock.patch("scripts.gar_lib.commands.setup.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("builtins.input", side_effect=["", "", "", "q"]),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_setup(no_install=True)

        self.assertEqual(1, result)
        text = output.getvalue()
        self.assertIn("未設定", text)
        self.assertIn("選択: Missing Test", text)
        self.assertIn("3. 実機環境", text)
        self.assertIn("未完了のセットアップ", text)

    def test_setup_saves_selected_provider_after_successful_setup(self) -> None:
        providers = [DevelopmentProvider]
        targets = [
            TargetManifest(
                id="test-target",
                display_name="Test Target",
                description="target",
                tools_root="targets/test",
                default_backends={},
                backend_notes={},
            ),
        ]
        config = {"selected_target": "test-target", "selected_providers": {}}

        with (
            mock.patch("scripts.gar_lib.commands.setup.discover_environment_providers", return_value=providers),
            mock.patch("scripts.gar_lib.commands.setup.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.save_config") as save_config,
            mock.patch("scripts.gar_lib.commands.setup.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("builtins.input", side_effect=["", "", "", "q"]),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_setup(no_install=True)

        self.assertEqual(0, result)
        save_config.assert_called_once_with(
            {"selected_target": "test-target", "selected_providers": {"codespace": "development_test"}}
        )

    def test_provider_dependency_success_message_names_provider(self) -> None:
        from scripts.gar_lib.commands.setup import ensure_provider_dependencies

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = ensure_provider_dependencies(DevelopmentProvider, no_install=True)

        self.assertEqual(0, result)
        self.assertIn("Development Test に必要なコマンドは見つかりました。", output.getvalue())
        self.assertNotIn("必要なコマンドはすべて見つかりました。", output.getvalue())

    def test_setup_saves_selected_target_when_interactive(self) -> None:
        providers = [DevelopmentProvider, WokwiProvider, TargetAccessProvider]
        targets = [
            TargetManifest(
                id="linux-device",
                display_name="Linux Device",
                description="linux",
                tools_root="targets/linux-device",
                default_backends={"simulator": "ssh_remote"},
                backend_notes={},
            ),
            TargetManifest(
                id="esp32",
                display_name="ESP32",
                description="esp32",
                tools_root="targets/esp32",
                default_backends={"codespace": "development_test", "simulator": "wokwi"},
                backend_notes={},
            ),
        ]
        config = {"selected_providers": {"codespace": "development_test"}}

        with (
            mock.patch("scripts.gar_lib.commands.setup.discover_environment_providers", return_value=providers),
            mock.patch("scripts.gar_lib.commands.setup.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.save_config") as save_config,
            mock.patch("scripts.gar_lib.commands.setup.configure_default_ec2_host"),
            mock.patch("scripts.gar_lib.commands.setup.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("sys.stdin.isatty", return_value=True),
            mock.patch("builtins.input", side_effect=["", "1", "2", "", "", "q"]),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_setup(no_install=True)

        self.assertEqual(0, result)
        save_config.assert_any_call(
            {"selected_target": "esp32", "selected_providers": {"codespace": "development_test"}}
        )
        text = output.getvalue()
        saved_at = text.index("更新しました: Target = ESP32")
        self.assertIn("1. Target", text[saved_at:])
        self.assertIn("2. 開発環境", text[saved_at:])
        self.assertIn("2. 開発環境\n  未設定", text[saved_at:])
        self.assertIn("3. シミュレート環境", text[saved_at:])
        self.assertIn("4. 実機環境", text[saved_at:])
        self.assertNotIn("未設定 Wokwi", text[saved_at:])
        self.assertNotIn("未設定 Development Test", text[saved_at:])

    def test_setup_unconfigured_target_does_not_show_default_candidate_as_status(self) -> None:
        providers = [DevelopmentProvider]
        targets = [
            TargetManifest(
                id="esp32",
                display_name="ESP32 / M5Stack",
                description="esp32 target",
                tools_root="targets/esp32",
                default_backends={},
                backend_notes={},
            ),
        ]
        config = {"selected_providers": {}}

        with (
            mock.patch("scripts.gar_lib.commands.setup.discover_environment_providers", return_value=providers),
            mock.patch("scripts.gar_lib.commands.setup.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("sys.stdin.isatty", return_value=True),
            mock.patch("builtins.input", side_effect=["", "q"]),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_setup(no_install=True)

        self.assertEqual(1, result)
        text = output.getvalue()
        self.assertIn("1. Target", text)
        self.assertIn("未設定", text)
        self.assertNotIn("未設定 ESP32 / M5Stack", text)
        self.assertNotIn("ESP32 / M5Stack (esp32)", text)
        self.assertIn("この項目を選ぶとTargetを選択できます。", text)

    def test_setup_reports_existing_wokwi_target(self) -> None:
        providers = [DevelopmentProvider, WokwiProvider]
        targets = [
            TargetManifest(
                id="esp32",
                display_name="ESP32",
                description="esp32",
                tools_root="targets/esp32",
                default_backends={"codespace": "development_test", "simulator": "wokwi"},
                backend_notes={},
            ),
        ]
        config = {
            "selected_target": "esp32",
            "selected_providers": {"codespace": "development_test"},
        }

        with (
            mock.patch("scripts.gar_lib.commands.setup.discover_environment_providers", return_value=providers),
            mock.patch("scripts.gar_lib.commands.setup.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.save_config") as save_config,
            mock.patch("scripts.gar_lib.commands.setup.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("sys.stdin.isatty", return_value=False),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_setup(no_install=True)

        self.assertEqual(0, result)
        save_config.assert_not_called()

    def test_setup_wokwi_flow_explains_required_and_optional_steps(self) -> None:
        providers = [DevelopmentProvider, WokwiProvider, MissingTargetAccessProvider]
        targets = [
            TargetManifest(
                id="esp32",
                display_name="ESP32 / M5Stack",
                description="esp32",
                tools_root="targets/esp32",
                default_backends={
                    "codespace": "development_test",
                    "simulator": "wokwi",
                    "target": "missing_test",
                },
                backend_notes={},
            ),
        ]
        config = {
            "selected_target": "esp32",
            "selected_providers": {"codespace": "development_test", "simulator": "wokwi", "target": "missing_test"},
        }

        with (
            mock.patch("scripts.gar_lib.commands.setup.discover_environment_providers", return_value=providers),
            mock.patch("scripts.gar_lib.commands.setup.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.save_config"),
            mock.patch("scripts.gar_lib.commands.setup.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("sys.stdin.isatty", return_value=False),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_setup(no_install=True)

        self.assertEqual(0, result)
        text = output.getvalue()
        self.assertNotIn("このTargetで使う接続先:", text)
        self.assertNotIn("画面上で動かすシミュレータ: Wokwi (wokwi)", text)
        self.assertNotIn("実機へ書き込む接続先: Missing Test (missing_test)", text)
        self.assertNotIn("ファームウェア起動確認", text)
        self.assertNotIn("PC上でリンク確認", text)
        self.assertNotIn("esp32_qemu_firmware", text)
        self.assertNotIn("fake-idf", text)
        self.assertNotIn("spp-jsonl", text)
        self.assertNotIn("recommended:", text)
        self.assertNotIn("このsetupで設定できること:", text)
        self.assertNotIn("Wokwi project + Wokwi CLI", text)
        self.assertNotIn("任意の設定:", text)
        self.assertNotIn("シミュレーション環境と実機書き込み環境は", text)
        self.assertNotIn("確認対象の状況:", text)
        self.assertIn("次の操作フェーズ", text)
        self.assertIn("make wokwi-workspace", text)
        self.assertIn("scripts/gar sim env build", text)
        self.assertIn("make wokwi-build を実行します", text)
        self.assertIn("scripts/gar sim env start --no-port-forward", text)
        self.assertIn("人間がUIを確認", text)
        self.assertIn("シミュレート環境", text)
        self.assertIn("実機環境", text)
        self.assertIn("後で設定可", text)
        self.assertIn("あとで設定できる項目", text)
        self.assertNotIn("未完了のセットアップ", text)

    def test_setup_allows_simulation_to_remain_unconfigured(self) -> None:
        providers = [DevelopmentProvider, MissingSimulationProvider]
        targets = [
            TargetManifest(
                id="linux-device",
                display_name="Linux Device",
                description="linux",
                tools_root="targets/linux-device",
                default_backends={
                    "codespace": "development_test",
                    "simulator": "missing_simulation",
                },
                backend_notes={},
            ),
        ]
        config = {
            "selected_target": "linux-device",
            "selected_providers": {
                "codespace": "development_test",
                "simulator": "missing_simulation",
            },
        }

        with (
            mock.patch("scripts.gar_lib.commands.setup.discover_environment_providers", return_value=providers),
            mock.patch("scripts.gar_lib.commands.setup.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("sys.stdin.isatty", return_value=False),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_setup(no_install=True)

        self.assertEqual(0, result)
        text = output.getvalue()
        self.assertIn("シミュレート環境", text)
        self.assertIn("後で設定可", text)
        self.assertIn("あとで設定できる項目", text)
        self.assertNotIn("未完了のセットアップ", text)

    def test_setup_defaults_to_optional_category_after_required_items(self) -> None:
        from scripts.gar_lib.commands.setup import first_unconfigured_category_index

        categories = [
            ("codespace", "開発環境", [DevelopmentProvider]),
            ("simulator", "シミュレート環境", [WokwiProvider]),
            ("target", "実機環境", [MissingTargetAccessProvider]),
        ]
        config = {
            "selected_providers": {
                "codespace": "development_test",
                "simulator": "wokwi",
                "target": "missing_test",
            }
        }

        selected_index = first_unconfigured_category_index(
            categories,
            config,
            optional_categories={"target"},
        )

        self.assertEqual(3, selected_index)

    def test_setup_existing_target_goes_to_environment_overview_without_target_prompt(self) -> None:
        providers = [DevelopmentProvider, WokwiProvider, TargetAccessProvider]
        targets = [
            TargetManifest(
                id="esp32",
                display_name="ESP32",
                description="esp32",
                tools_root="targets/esp32",
                default_backends={"codespace": "development_test", "simulator": "wokwi", "target": "device_test"},
                backend_notes={},
            ),
            TargetManifest(
                id="linux-device",
                display_name="Linux Device",
                description="linux",
                tools_root="targets/linux-device",
                default_backends={"codespace": "development_test", "simulator": "simulation_test", "target": "device_test"},
                backend_notes={},
            ),
        ]
        config = {
            "selected_target": "esp32",
            "selected_providers": {
                "codespace": "development_test",
                "simulator": "wokwi",
                "target": "device_test",
                "boot": "esp32_qemu_firmware",
                "hostLink": "fake-idf",
                "probe": "spp-jsonl",
            },
        }

        with (
            mock.patch("scripts.gar_lib.commands.setup.discover_environment_providers", return_value=providers),
            mock.patch("scripts.gar_lib.commands.setup.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.save_config") as save_config,
            mock.patch("scripts.gar_lib.commands.setup.configure_default_ec2_host"),
            mock.patch("scripts.gar_lib.commands.setup.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("sys.stdin.isatty", return_value=True),
            mock.patch("builtins.input", side_effect=["", ""]),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_setup(no_install=True)

        self.assertEqual(0, result)
        save_config.assert_called_once_with(
            {
                "selected_target": "esp32",
                "selected_providers": {
                    "codespace": "development_test",
                    "simulator": "wokwi",
                    "target": "device_test",
                },
            }
        )
        text = output.getvalue()
        self.assertLess(text.index("1. Target"), text.index("2. 開発環境"))
        self.assertNotIn("Target を変更しますか", text)

    def test_setup_configured_category_no_change_returns_to_overview(self) -> None:
        providers = [DevelopmentProvider, SimulationProvider]
        targets = [
            TargetManifest(
                id="test-target",
                display_name="Test Target",
                description="target",
                tools_root="targets/test",
                default_backends={
                    "codespace": "development_test",
                    "simulator": "simulation_test",
                },
                backend_notes={},
            ),
        ]
        config = {
            "selected_target": "test-target",
            "selected_providers": {
                "codespace": "development_test",
                "simulator": "simulation_test",
            },
        }

        with (
            mock.patch("scripts.gar_lib.commands.setup.discover_environment_providers", return_value=providers),
            mock.patch("scripts.gar_lib.commands.setup.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.configure_default_ec2_host"),
            mock.patch("scripts.gar_lib.commands.setup.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("sys.stdin.isatty", return_value=True),
            mock.patch("builtins.input", side_effect=["", "2", "", "q"]),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_setup(no_install=True)

        self.assertEqual(0, result)
        text = output.getvalue()
        first_overview = text.index("2. 開発環境")
        second_overview = text.index("2. 開発環境", first_overview + 1)
        self.assertGreater(second_overview, first_overview)
        self.assertIn("3. シミュレート環境", text[second_overview:])

    def test_setup_prunes_backends_removed_from_target_defaults(self) -> None:
        providers = [DevelopmentProvider, WokwiProvider, TargetAccessProvider]
        targets = [
            TargetManifest(
                id="esp32",
                display_name="ESP32",
                description="esp32",
                tools_root="targets/esp32",
                default_backends={"codespace": "development_test", "simulator": "wokwi", "target": "device_test"},
                backend_notes={},
            ),
        ]
        config = {
            "selected_target": "esp32",
            "selected_providers": {
                "codespace": "development_test",
                "simulator": "wokwi",
                "target": "device_test",
                "boot": "esp32_qemu_firmware",
                "hostLink": "fake-idf",
                "probe": "spp-jsonl",
            },
        }

        with (
            mock.patch("scripts.gar_lib.commands.setup.discover_environment_providers", return_value=providers),
            mock.patch("scripts.gar_lib.commands.setup.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.save_config") as save_config,
            mock.patch("scripts.gar_lib.commands.setup.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("sys.stdin.isatty", return_value=False),
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                result = run_setup(no_install=True)

        self.assertEqual(0, result)
        save_config.assert_called_once_with(
            {
                "selected_target": "esp32",
                "selected_providers": {
                    "codespace": "development_test",
                    "simulator": "wokwi",
                    "target": "device_test",
                },
            }
        )

    def test_setup_provider_selection_accepts_quit(self) -> None:
        providers = [DevelopmentProvider]
        config = {"selected_providers": {}}

        with (
            mock.patch("scripts.gar_lib.commands.setup.discover_environment_providers", return_value=providers),
            mock.patch("scripts.gar_lib.commands.setup.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("builtins.input", side_effect=["", "q"]),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_setup(no_install=True)

        self.assertEqual(1, result)
        self.assertIn("未完了のセットアップ", output.getvalue())

    def test_terminal_run_creates_vscode_terminal_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with (
                mock.patch("scripts.gar_lib.commands.terminal.CONFIG_PATH", tmp_path / ".gar" / "config.json"),
                mock.patch("scripts.gar_lib.commands.terminal.Path.cwd", return_value=tmp_path),
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = run_terminal_request(
                        command_parts=["echo", "hello"],
                        command_text=None,
                        title="Test Terminal",
                        cwd=None,
                    )

            self.assertEqual(0, result)
            requests = list((tmp_path / ".gar" / "terminal-requests").glob("*.json"))
            self.assertEqual(1, len(requests))

            request = json.loads(requests[0].read_text(encoding="utf-8"))
            self.assertEqual("Test Terminal", request["title"])
            self.assertEqual("echo hello", request["command"])
            self.assertEqual(str(tmp_path), request["cwd"])

    def test_sim_infra_setup_shows_settings_and_runs_terraform_plan(self) -> None:
        completed = mock.Mock(returncode=0, stdout="", stderr="")
        output_result = mock.Mock(
            returncode=0,
            stdout=json.dumps(
                {
                    "instance_id": {"value": "i-from-tf"},
                    "public_ip": {"value": "203.0.113.55"},
                }
            ),
            stderr="",
        )
        config = {
            "selected_providers": {},
            "ec2": {"host": "configured-ec2", "region": "ap-test-1"},
        }

        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch("scripts.gar_lib.commands.infra.TERRAFORM_DIR", Path(tmp)),
                mock.patch("scripts.gar_lib.commands.infra._terraform_available", return_value=True),
                mock.patch("scripts.gar_lib.commands.infra.load_config", return_value=config),
                mock.patch(
                    "scripts.gar_lib.commands.infra._run_terraform",
                    side_effect=[completed, output_result, completed],
                ) as run_tf,
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = run_sim_infra_command(
                        "setup",
                        key_name="gar-key",
                        region="ap-test-2",
                    )

        self.assertEqual(0, result)
        self.assertEqual(["init", "-input=false"], run_tf.call_args_list[0].args[0])
        self.assertEqual(["output", "-json"], run_tf.call_args_list[1].args[0])
        self.assertEqual(["plan", "-input=false"], run_tf.call_args_list[2].args[0])
        env = run_tf.call_args_list[2].kwargs["env"]
        self.assertEqual("ap-test-2", env["TF_VAR_aws_region"])
        self.assertEqual("gar-key", env["TF_VAR_key_name"])
        self.assertIn("Current simulation infra settings:", output.getvalue())
        self.assertIn("i-from-tf", output.getvalue())

    def test_sim_infra_apply_saves_instance_and_updates_ssh(self) -> None:
        init_result = mock.Mock(returncode=0, stdout="", stderr="")
        apply_result = mock.Mock(returncode=0, stdout="", stderr="")
        output_result = mock.Mock(
            returncode=0,
            stdout=json.dumps(
                {
                    "instance_id": {"value": "i-from-tf"},
                    "public_ip": {"value": "203.0.113.55"},
                }
            ),
            stderr="",
        )
        config = {
            "selected_providers": {},
            "ec2": {"host": "configured-ec2", "region": "ap-test-1"},
        }

        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch("scripts.gar_lib.commands.infra.TERRAFORM_DIR", Path(tmp)),
                mock.patch("scripts.gar_lib.commands.infra._terraform_available", return_value=True),
                mock.patch("scripts.gar_lib.commands.infra.load_config", return_value=config),
                mock.patch("scripts.gar_lib.commands.infra.save_config") as save_config,
                mock.patch(
                    "scripts.gar_lib.commands.infra._run_terraform",
                    side_effect=[init_result, apply_result, output_result],
                ) as run_tf,
                mock.patch("scripts.gar_lib.commands.infra.SshConfigHostAddressUpdater") as updater_type,
            ):
                updater_type.return_value.update.return_value = True
                result = run_sim_infra_command(
                    "apply",
                    region="ap-test-2",
                    auto_approve=True,
                )

        self.assertEqual(0, result)
        self.assertEqual(["apply", "-input=false", "-auto-approve"], run_tf.call_args_list[1].args[0])
        saved_config = save_config.call_args.args[0]
        self.assertEqual("i-from-tf", saved_config["ec2"]["instance_id"])
        self.assertEqual("ap-test-2", saved_config["ec2"]["region"])
        updater_type.return_value.update.assert_called_once_with("configured-ec2", "203.0.113.55")

    def test_update_ssh_config_hostname_rewrites_target_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config"
            config_path.write_text(
                "Host other\n"
                "    HostName 198.51.100.1\n"
                "\n"
                "Host vibecode-graviton\n"
                "    HostName 192.0.2.1\n"
                "    User ubuntu\n",
                encoding="utf-8",
            )

            updated = SshConfigHostAddressUpdater(config_path).update(
                "vibecode-graviton", "203.0.113.5"
            )

            self.assertTrue(updated)
            contents = config_path.read_text(encoding="utf-8")
            self.assertIn("HostName 203.0.113.5", contents)
            self.assertIn("HostName 198.51.100.1", contents)

    def test_update_ssh_config_hostname_adds_missing_hostname(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config"
            config_path.write_text(
                "Host vibecode-graviton\n"
                "    User ubuntu\n"
                "    IdentityFile ~/.ssh/vibecode-graviton.pem\n",
                encoding="utf-8",
            )

            updated = SshConfigHostAddressUpdater(config_path).update(
                "vibecode-graviton", "203.0.113.5"
            )

            self.assertTrue(updated)
            self.assertIn("    HostName 203.0.113.5\n", config_path.read_text(encoding="utf-8"))

    def test_usb_list_parses_usbipd_output(self) -> None:
        output = (
            "Connected:\n"
            "BUSID  VID:PID    DEVICE                                STATE\n"
            "1-4    8087:0aaa  Intel(R) Wireless Bluetooth(R)        Not shared\n"
            "2-3    18d1:4ee7  Android ADB Interface, USB Mass...    Shared\n"
            "\n"
            "Persisted:\n"
            "GUID  DEVICE\n"
        )
        devices = parse_usbipd_list(output)

        self.assertEqual(2, len(devices))
        android = devices[1]
        self.assertEqual("2-3", android.busid)
        self.assertEqual("18d1:4ee7", android.vid_pid)
        self.assertEqual("Shared", android.state)
        self.assertTrue(android.is_shared)
        self.assertTrue(android.looks_like_android)
        self.assertFalse(devices[0].looks_like_android)

    def test_usb_attach_auto_detects_android_and_remembers_busid(self) -> None:
        output = (
            "Connected:\n"
            "BUSID  VID:PID    DEVICE             STATE\n"
            "2-3    18d1:4ee7  Android ADB        Shared\n"
        )
        saved: dict = {}
        with (
            mock.patch("scripts.gar_lib.commands.usb._usbipd_executable", return_value="usbipd.exe"),
            mock.patch(
                "scripts.gar_lib.commands.usb.list_usb_devices",
                return_value=parse_usbipd_list(output),
            ),
            mock.patch("scripts.gar_lib.commands.usb.load_config", return_value={"selected_providers": {}}),
            mock.patch("scripts.gar_lib.commands.usb.save_config", side_effect=lambda c: saved.update(c)),
            mock.patch("scripts.gar_lib.commands.usb._run_usbipd") as run_usbipd,
        ):
            run_usbipd.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            output_buffer = io.StringIO()
            with contextlib.redirect_stdout(output_buffer):
                result = run_usb_command("attach")

        self.assertEqual(0, result)
        run_usbipd.assert_called_once_with(["attach", "--wsl", "--busid", "2-3"])
        self.assertEqual("2-3", saved.get("usb", {}).get("busid"))

    def test_usb_attach_can_match_ch9102_serial_device(self) -> None:
        output = (
            "Connected:\n"
            "BUSID  VID:PID    DEVICE                         STATE\n"
            "3-4    1a86:55d4  USB-Enhanced-SERIAL CH9102      Shared\n"
        )
        saved: dict = {}
        with (
            mock.patch("scripts.gar_lib.commands.usb._usbipd_executable", return_value="usbipd.exe"),
            mock.patch(
                "scripts.gar_lib.commands.usb.list_usb_devices",
                return_value=parse_usbipd_list(output),
            ),
            mock.patch("scripts.gar_lib.commands.usb.load_config", return_value={"selected_providers": {}}),
            mock.patch("scripts.gar_lib.commands.usb.save_config", side_effect=lambda c: saved.update(c)),
            mock.patch("scripts.gar_lib.commands.usb._run_usbipd") as run_usbipd,
        ):
            run_usbipd.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            result = run_usb_command("attach", match="CH9102")

        self.assertEqual(0, result)
        run_usbipd.assert_called_once_with(["attach", "--wsl", "--busid", "3-4"])
        self.assertEqual("3-4", saved.get("usb", {}).get("busid"))

    def test_usb_bind_can_match_ch9102_serial_device(self) -> None:
        output = (
            "Connected:\n"
            "BUSID  VID:PID    DEVICE                         STATE\n"
            "3-4    1a86:55d4  USB-Enhanced-SERIAL CH9102      Not shared\n"
        )
        with (
            mock.patch("scripts.gar_lib.commands.usb._usbipd_executable", return_value="usbipd.exe"),
            mock.patch(
                "scripts.gar_lib.commands.usb.list_usb_devices",
                return_value=parse_usbipd_list(output),
            ),
            mock.patch("scripts.gar_lib.commands.usb.load_config", return_value={"selected_providers": {}}),
            mock.patch("scripts.gar_lib.commands.usb.save_config"),
            mock.patch("scripts.gar_lib.commands.usb._run_usbipd") as run_usbipd,
        ):
            run_usbipd.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            result = run_usb_command("bind", match="CH9102")

        self.assertEqual(0, result)
        run_usbipd.assert_called_once_with(["bind", "--busid", "3-4"])

    def test_usb_attach_hints_bind_when_not_shared(self) -> None:
        output = (
            "Connected:\n"
            "BUSID  VID:PID    DEVICE             STATE\n"
            "2-3    18d1:4ee7  Android ADB        Not shared\n"
        )
        with (
            mock.patch("scripts.gar_lib.commands.usb._usbipd_executable", return_value="usbipd.exe"),
            mock.patch(
                "scripts.gar_lib.commands.usb.list_usb_devices",
                return_value=parse_usbipd_list(output),
            ),
            mock.patch("scripts.gar_lib.commands.usb.load_config", return_value={"selected_providers": {}}),
            mock.patch("scripts.gar_lib.commands.usb._run_usbipd") as run_usbipd,
        ):
            err_buffer = io.StringIO()
            with contextlib.redirect_stderr(err_buffer):
                result = run_usb_command("attach")

        self.assertEqual(1, result)
        run_usbipd.assert_not_called()
        self.assertIn("gar usb bind --busid 2-3", err_buffer.getvalue())
        self.assertIn("usbipd bind --busid 2-3", err_buffer.getvalue())
        self.assertIn("Host OS", err_buffer.getvalue())
        self.assertIn("管理者権限", err_buffer.getvalue())

    def test_usb_bind_admin_error_hints_windows_usbipd_command(self) -> None:
        output = (
            "Connected:\n"
            "BUSID  VID:PID    DEVICE                      STATE\n"
            "4-2    1a86:55d4  USB-Enhanced-SERIAL CH9102  Not shared\n"
        )
        with (
            mock.patch("scripts.gar_lib.commands.usb._usbipd_executable", return_value="usbipd.exe"),
            mock.patch(
                "scripts.gar_lib.commands.usb.list_usb_devices",
                return_value=parse_usbipd_list(output),
            ),
            mock.patch("scripts.gar_lib.commands.usb.load_config", return_value={"selected_providers": {}}),
            mock.patch("scripts.gar_lib.commands.usb._run_usbipd") as run_usbipd,
        ):
            run_usbipd.return_value = mock.Mock(
                returncode=1,
                stdout="",
                stderr="usbipd: error: Access denied; this operation requires administrator privileges.",
            )
            err_buffer = io.StringIO()
            with contextlib.redirect_stderr(err_buffer):
                result = run_usb_command("bind", match="CH9102")

        self.assertEqual(1, result)
        run_usbipd.assert_called_once_with(["bind", "--busid", "4-2"])
        self.assertIn("Access denied", err_buffer.getvalue())
        self.assertIn("Host OS の usbipd bind", err_buffer.getvalue())
        self.assertIn("管理者権限不足でエラー", err_buffer.getvalue())
        self.assertIn("管理者権限で開いて", err_buffer.getvalue())
        self.assertIn("usbipd bind --busid 4-2", err_buffer.getvalue())
        self.assertIn("gar usb attach --busid 4-2", err_buffer.getvalue())

    def test_sim_gpio_plan_builds_gpio_sim_contract(self) -> None:
        hw_definition = {
            "gpio": [
                {
                    "name": "test_button",
                    "chip": "/dev/gpiochip2",
                    "line": "5",
                    "direction": "input",
                    "role": "button",
                    "sim_control": "pull",
                },
                {
                    "name": "test_led",
                    "chip": "/dev/gpiochip2",
                    "line": "6",
                    "direction": "output",
                    "role": "led",
                    "sim_control": "value",
                },
            ],
        }

        plan = gpio_sim_plan(hw_definition)

        self.assertEqual("gpio-sim", plan["driver"])
        self.assertEqual("/dev/gpiochip2", plan["target_device"])
        self.assertEqual(54, plan["num_lines"])
        self.assertEqual("BTN_GPIO5", plan["lines"][0]["label"])
        self.assertEqual("LED_GPIO6", plan["lines"][1]["label"])

    def test_sim_env_deploy_accepts_workspace_name(self) -> None:
        with mock.patch("scripts.gar_lib.cli.execute_application_command", return_value=0) as run_deploy:
            result = main(["sim", "env", "deploy", "--workspace", "Local/GarStreamTx"])

        self.assertEqual(0, result)
        run_deploy.assert_called_once_with(
            SIM_RUNTIME_DEPLOY,
            workspace_selector="Local/GarStreamTx",
            retry_command="gar sim env deploy --workspace Local/GarStreamTx",
        )

    def test_sim_build_is_available_from_cli(self) -> None:
        with mock.patch("scripts.gar_lib.cli.execute_application_command", return_value=0) as run_build:
            result = main(["sim", "build", "--workspace", "local/GarStreamRx"])

        self.assertEqual(0, result)
        run_build.assert_called_once_with(
            SIM_BUILD,
            workspace_selector="local/GarStreamRx",
            retry_command="gar sim build --workspace local/GarStreamRx",
        )

    def test_sim_build_uses_product_provider_environment(self) -> None:
        with mock.patch("scripts.gar_lib.cli.execute_application_command", return_value=0) as run_product_build:
            result = main(["sim", "build"])

        self.assertEqual(0, result)
        run_product_build.assert_called_once_with(
            SIM_BUILD,
            workspace_selector=None,
            retry_command="gar sim build",
        )

    def test_sim_build_accepts_setup_workspace_name(self) -> None:
        with mock.patch("scripts.gar_lib.cli.execute_application_command", return_value=0) as run_build:
            result = main(["sim", "build", "--workspace", "local/GarStreamRx"])

        self.assertEqual(0, result)
        run_build.assert_called_once_with(
            SIM_BUILD,
            workspace_selector="local/GarStreamRx",
            retry_command="gar sim build --workspace local/GarStreamRx",
        )

    def test_sim_env_build_uses_environment_command_path(self) -> None:
        with mock.patch("scripts.gar_lib.cli.execute_application_command", return_value=0) as run_build:
            result = main(["sim", "env", "build", "--workspace", "Local/GarStreamTx"])

        self.assertEqual(0, result)
        run_build.assert_called_once_with(
            SIM_RUNTIME_BUILD,
            workspace_selector="Local/GarStreamTx",
            retry_command="gar sim env build --workspace Local/GarStreamTx",
        )

    def test_sim_build_clean_is_available_from_cli(self) -> None:
        with mock.patch("scripts.gar_lib.cli.execute_application_command", return_value=0) as run_sim:
            result = main(["sim", "build", "clean", "--workspace", "local/GarStreamRx"])

        self.assertEqual(0, result)
        run_sim.assert_called_once_with(
            SIM_CLEAN,
            workspace_selector="local/GarStreamRx",
            retry_command="gar sim build clean --workspace local/GarStreamRx",
        )

    def test_sim_build_rejects_workspace_root_option(self) -> None:
        with self.assertRaises(SystemExit):
            main(["sim", "build", "--workspace-root", "/tmp/product"])

    def test_sim_status_accepts_workspace_name(self) -> None:
        with mock.patch("scripts.gar_lib.cli.execute_application_command", return_value=0) as run_host:
            result = main(["sim", "status", "--workspace", "Local/GarStreamTx"])

        self.assertEqual(0, result)
        run_host.assert_called_once_with(
            SIM_HOST_STATUS,
            workspace_selector="Local/GarStreamTx",
            retry_command="gar sim status --workspace Local/GarStreamTx",
            update_address=True,
            update_repository=False,
            json_output=False,
        )

    def test_sim_start_workspace_uses_host_controller_options(self) -> None:
        with mock.patch("scripts.gar_lib.cli.execute_application_command", return_value=0) as run_host:
            result = main(
                [
                    "sim",
                    "start",
                    "--workspace",
                    "Local/GarStreamTx",
                    "--no-update-ssh",
                    "--pull",
                ]
            )

        self.assertEqual(0, result)
        run_host.assert_called_once_with(
            SIM_HOST_START,
            workspace_selector="Local/GarStreamTx",
            retry_command="gar sim start --workspace Local/GarStreamTx",
            update_address=False,
            update_repository=True,
            json_output=False,
        )

    def test_sim_stop_workspace_uses_host_controller(self) -> None:
        with mock.patch("scripts.gar_lib.cli.execute_application_command", return_value=0) as run_host:
            result = main(["sim", "stop", "--workspace", "Local/GarStreamTx"])

        self.assertEqual(0, result)
        run_host.assert_called_once_with(
            SIM_HOST_STOP,
            workspace_selector="Local/GarStreamTx",
            retry_command="gar sim stop --workspace Local/GarStreamTx",
            update_address=True,
            update_repository=False,
            json_output=False,
        )

    def test_sim_infra_setup_is_available_from_cli(self) -> None:
        with mock.patch("scripts.gar_lib.cli.run_sim_infra_command", return_value=0) as run_infra:
            result = main(["sim", "infra", "setup", "--region", "ap-test-1", "--key-name", "gar-key"])

        self.assertEqual(0, result)
        run_infra.assert_called_once_with(
            "setup",
            key_name="gar-key",
            region="ap-test-1",
            auto_approve=False,
        )

    def test_sim_infra_output_is_not_a_public_cli_command(self) -> None:
        with (
            mock.patch("scripts.gar_lib.cli.run_sim_infra_command") as run_infra,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(SystemExit) as exc:
                main(["sim", "infra", "output"])

        self.assertEqual(2, exc.exception.code)
        run_infra.assert_not_called()

    def test_target_deploy_workspace_uses_target_environment(self) -> None:
        with mock.patch("scripts.gar_lib.cli.execute_application_command", return_value=0) as deploy:
            result = main(["target", "deploy", "--workspace", "Local/Product"])

        self.assertEqual(0, result)
        deploy.assert_called_once_with(
            TARGET_DEPLOY,
            workspace_selector="Local/Product",
            retry_command="gar target deploy --workspace Local/Product",
        )

    def test_target_deploy_rejects_legacy_connection_overrides(self) -> None:
        for option, value in (
            ("--serial", "device-1"),
            ("--port", "COM3"),
            ("--host", "raspi"),
            ("--dest", "/opt/product"),
            ("--artifacts-dir", "/tmp/artifacts"),
            ("--codespace", "product-space"),
            ("--remote-root", "/workspaces/product"),
        ):
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    main(["target", "deploy", option, value])

            self.assertEqual(2, raised.exception.code)

    def test_target_fetch_copies_manifest_sources_from_codespace(self) -> None:
        manifest = {
            "name": "sensor-demo",
            "deploy": {
                "app": {
                    "files": [
                        {"src": "files/sensor_demo", "dest": "/home/user/sensor_demo", "mode": "0755"}
                    ]
                },
                "sim_env": {
                    "files": [
                        {"src": "files/cuse_i2c", "dest": "~/cuse_i2c", "mode": "0755"},
                        {"src": "files/web-bridge", "dest": "~/web-bridge"},
                    ]
                },
            },
        }

        def fake_cp(
            codespace: str,
            remote_path: str,
            local_path: Path,
            *,
            recursive: bool = False,
        ) -> subprocess.CompletedProcess:
            self.assertEqual("codespace-test", codespace)
            if remote_path.endswith("/artifact.json"):
                local_path.write_text(json.dumps(manifest), encoding="utf-8")
                return subprocess.CompletedProcess(args=[], returncode=0)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            if remote_path.endswith("/files/web-bridge"):
                local_path.mkdir(parents=True, exist_ok=True)
                (local_path / "bridge.py").write_text("", encoding="utf-8")
            else:
                local_path.write_text("", encoding="utf-8")
            self.assertTrue(recursive)
            return subprocess.CompletedProcess(args=[], returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                mock.patch("scripts.gar_lib.artifacts.manifest.select_codespace", return_value="codespace-test"),
                mock.patch("scripts.gar_lib.artifacts.manifest.gh_codespace_cp", side_effect=fake_cp) as cp,
            ):
                result = fetch_codespace_artifacts(root, remote_root="/workspaces/out")

            written_manifest = json.loads((root / "artifact.json").read_text(encoding="utf-8"))

        self.assertEqual(0, result)
        self.assertEqual(manifest, written_manifest)
        self.assertEqual(4, cp.call_count)

    def test_target_fetch_is_available_from_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("scripts.gar_lib.cli.fetch_codespace_artifacts", return_value=0) as fetch:
                result = main(
                    [
                        "target",
                        "fetch",
                        "--codespace",
                        "codespace-test",
                        "--remote-root",
                        "/workspaces/out",
                        "--artifacts-dir",
                        str(root),
                    ]
                )

        self.assertEqual(0, result)
        fetch.assert_called_once_with(
            root.resolve(),
            codespace="codespace-test",
            remote_root="/workspaces/out",
        )

    def test_esp32_serial_port_maps_windows_com_to_wsl_tty(self) -> None:
        self.assertEqual("/dev/ttyS3", normalize_esp32_serial_port("COM3"))

    def test_esp32_serial_port_uses_setup_saved_port(self) -> None:
        with mock.patch("scripts.gar_lib.target.esptool.load_config", return_value={"esp32": {"port": "COM4"}}):
            self.assertEqual("/dev/ttyS4", normalize_esp32_serial_port(None))

    def test_esp32_build_output_parses_artifact_path(self) -> None:
        output = "\n".join(
            [
                "[3/3] Done",
                "Artifact: /workspaces/project/artifacts/20260620-001750-m5stickc-plus2-vibe-min",
                "Next: ./scripts/install_artifact.sh ...",
            ]
        )

        self.assertEqual(
            "/workspaces/project/artifacts/20260620-001750-m5stickc-plus2-vibe-min",
            parse_esp32_build_artifact_path(output),
        )

    def test_target_build_esp32_builds_fetches_and_flashes(self) -> None:
        build_output = (
            "[1/3] Build firmware in VM\n"
            "Artifact: /workspaces/gar-build-env/repos/apps/gar-vibe-ui/vibe-remote/m5stickc-client/"
            "artifacts/20260620-001750-m5stickc-plus2-vibe-min\n"
        )
        local_artifact = Path("/tmp/local-artifacts/20260620-001750-m5stickc-plus2-vibe-min")

        with (
            mock.patch("scripts.gar_lib.targets.esp32.select_codespace", return_value="codespace-test"),
            mock.patch(
                "scripts.gar_lib.targets.esp32.run_streaming_command",
                return_value=(0, build_output),
            ) as run,
            mock.patch(
                "scripts.gar_lib.targets.esp32.fetch_esp32_codespace_artifact",
                return_value=local_artifact,
            ) as fetch,
            mock.patch("scripts.gar_lib.target.esptool.run_esp32_flash_command", return_value=0) as flash,
        ):
            result = run_esp32_build_command(
                codespace=None,
                remote_project_root="/workspaces/project",
                pio_env="m5stickc-plus2-vibe-min",
                local_artifact_root="/tmp/local-artifacts",
                flash=True,
                port="/dev/ttyACM0",
                baud=460800,
                chip="esp32",
                verify=False,
                install_esptool=False,
            )

        self.assertEqual(0, result)
        run.assert_called_once()
        self.assertEqual(
            ["gh", "codespace", "ssh", "-c", "codespace-test", "--"],
            run.call_args.args[0][:6],
        )
        self.assertIn("./scripts/vm_build_and_package.sh m5stickc-plus2-vibe-min", run.call_args.args[0][-1])
        fetch.assert_called_once_with(
            "/workspaces/gar-build-env/repos/apps/gar-vibe-ui/vibe-remote/m5stickc-client/"
            "artifacts/20260620-001750-m5stickc-plus2-vibe-min",
            codespace="codespace-test",
            local_artifact_root=Path("/tmp/local-artifacts"),
        )
        flash.assert_called_once_with(
            artifact_dir=str(local_artifact),
            port="/dev/ttyACM0",
            baud=460800,
            chip="esp32",
            verify=False,
            install_esptool=False,
        )

    def test_target_flash_esp32_verifies_and_invokes_esptool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for filename in (
                "bootloader.bin",
                "partitions.bin",
                "boot_app0.bin",
                "firmware.bin",
            ):
                (root / filename).write_bytes(f"{filename}\n".encode())
            sums = []
            for filename in (
                "boot_app0.bin",
                "bootloader.bin",
                "firmware.bin",
                "partitions.bin",
            ):
                digest = hashlib.sha256((root / filename).read_bytes()).hexdigest()
                sums.append(f"{digest}  {filename}\n")
            (root / "SHA256SUMS").write_text("".join(sums), encoding="utf-8")

            completed = mock.Mock(returncode=0)
            with (
                mock.patch(
                    "scripts.gar_lib.target.esptool.ensure_esptool_python",
                    return_value=Path("/opt/gar-esptool/bin/python"),
                ),
                mock.patch(
                    "scripts.gar_lib.target.esptool.esp32_serial_port_access_error",
                    return_value=None,
                ),
                mock.patch(
                    "scripts.gar_lib.target.esptool.subprocess.run",
                    return_value=completed,
                ) as run,
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = run_esp32_flash_command(
                        artifact_dir=str(root),
                        port="COM3",
                        baud=460800,
                    )

        self.assertEqual(0, result)
        args = run.call_args.args[0]
        self.assertEqual("/opt/gar-esptool/bin/python", args[0])
        self.assertIn("--port", args)
        self.assertEqual("/dev/ttyS3", args[args.index("--port") + 1])
        self.assertIn("--baud", args)
        self.assertEqual("460800", args[args.index("--baud") + 1])
        self.assertIn("0x10000", args)
        self.assertTrue(str(root / "firmware.bin") in args)
        self.assertIn("write-flash", args)
        self.assertIn("Flash complete.", output.getvalue())

    def test_target_flash_esp32_stops_before_esptool_when_serial_port_is_inaccessible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for filename in (
                "bootloader.bin",
                "partitions.bin",
                "boot_app0.bin",
                "firmware.bin",
            ):
                (root / filename).write_bytes(b"ok")

            with (
                mock.patch(
                    "scripts.gar_lib.target.esptool.esp32_serial_port_access_error",
                    return_value="serial port is not readable/writable by current user: /dev/ttyS3",
                ),
                mock.patch("scripts.gar_lib.target.esptool.ensure_esptool_python") as ensure_esptool,
            ):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    result = run_esp32_flash_command(
                        artifact_dir=str(root),
                        port="COM3",
                        verify=False,
                    )

        self.assertEqual(1, result)
        ensure_esptool.assert_not_called()
        self.assertIn("not readable/writable", err.getvalue())

    def test_target_flash_esp32_hints_usbipd_when_wsl_com_flash_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for filename in (
                "bootloader.bin",
                "partitions.bin",
                "boot_app0.bin",
                "firmware.bin",
            ):
                (root / filename).write_bytes(b"ok")

            completed = mock.Mock(returncode=2)
            with (
                mock.patch(
                    "scripts.gar_lib.target.esptool.ensure_esptool_python",
                    return_value=Path("/opt/gar-esptool/bin/python"),
                ),
                mock.patch(
                    "scripts.gar_lib.target.esptool.esp32_serial_port_access_error",
                    return_value=None,
                ),
                mock.patch(
                    "scripts.gar_lib.target.esptool.subprocess.run",
                    return_value=completed,
                ),
            ):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    result = run_esp32_flash_command(
                        artifact_dir=str(root),
                        port="COM3",
                        verify=False,
                    )

        self.assertEqual(2, result)
        self.assertIn("usbipd", err.getvalue())
        self.assertIn("/dev/ttyUSB0", err.getvalue())

    def test_target_flash_esp32_is_available_from_cli(self) -> None:
        with mock.patch(
            "scripts.gar_lib.cli.run_esp32_flash_command",
            return_value=0,
        ) as flash:
            result = main(
                [
                    "target",
                    "flash-esp32",
                    "--artifact-dir",
                    "/tmp/m5-artifact",
                    "--port",
                    "COM3",
                    "--baud",
                    "460800",
                    "--no-verify",
                    "--no-install-esptool",
                ]
            )

        self.assertEqual(0, result)
        flash.assert_called_once_with(
            artifact_dir="/tmp/m5-artifact",
            port="COM3",
            baud=460800,
            chip="esp32",
            verify=False,
            install_esptool=False,
        )

    def test_target_build_esp32_is_available_from_cli(self) -> None:
        with mock.patch(
            "scripts.gar_lib.cli.run_esp32_build_command",
            return_value=0,
        ) as build:
            result = main(
                [
                    "target",
                    "build-esp32",
                    "--codespace",
                    "codespace-test",
                    "--remote-project-root",
                    "/workspaces/project",
                    "--pio-env",
                    "m5stickc-plus2-vibe-min",
                    "--artifact-root",
                    "/tmp/artifacts",
                    "--flash",
                    "--port",
                    "/dev/ttyACM0",
                    "--baud",
                    "460800",
                    "--no-verify",
                    "--no-install-esptool",
                ]
            )

        self.assertEqual(0, result)
        build.assert_called_once_with(
            codespace="codespace-test",
            remote_project_root="/workspaces/project",
            pio_env="m5stickc-plus2-vibe-min",
            local_artifact_root="/tmp/artifacts",
            flash=True,
            port="/dev/ttyACM0",
            baud=460800,
            chip="esp32",
            verify=False,
            install_esptool=False,
        )

    def test_target_build_is_available_from_cli(self) -> None:
        with mock.patch("scripts.gar_lib.cli.execute_application_command", return_value=0) as build:
            result = main(["target", "build", "--workspace", "Codespaces/Product"])

        self.assertEqual(0, result)
        build.assert_called_once_with(
            TARGET_BUILD,
            workspace_selector="Codespaces/Product",
            retry_command="gar target build --workspace Codespaces/Product",
        )

    def test_code_start_is_available_from_cli(self) -> None:
        with mock.patch("scripts.gar_lib.cli.run_code_command", return_value=0) as run_code:
            result = main(["code", "start", "--codespace", "codespace-test", "--no-mount"])

        self.assertEqual(0, result)
        run_code.assert_called_once_with(
            "start",
            codespace="codespace-test",
            remote_path=None,
            mount_dir=None,
            settings=None,
            profile_name=None,
            no_mount=True,
            shutdown=False,
        )

    def test_code_boot_is_available_from_cli(self) -> None:
        with mock.patch("scripts.gar_lib.cli.run_code_command", return_value=0) as run_code:
            result = main(["code", "boot", "--codespace", "codespace-test"])

        self.assertEqual(0, result)
        run_code.assert_called_once_with(
            "boot",
            codespace="codespace-test",
            remote_path=None,
            mount_dir=None,
            settings=None,
            profile_name=None,
            no_mount=False,
            shutdown=False,
        )

    def test_code_status_is_available_from_cli(self) -> None:
        with mock.patch("scripts.gar_lib.cli.run_code_command", return_value=0) as run_code:
            result = main(["code", "status", "--codespace", "codespace-test", "--mount-dir", "/tmp/codespaces"])

        self.assertEqual(0, result)
        run_code.assert_called_once_with(
            "status",
            codespace="codespace-test",
            remote_path=None,
            mount_dir="/tmp/codespaces",
            settings=None,
            profile_name=None,
            no_mount=False,
            shutdown=False,
        )

    def test_code_command_uses_selected_codespaces_environment(self) -> None:
        with (
            mock.patch(
                "scripts.gar_lib.commands.code.load_config",
                return_value={"selected_providers": {"codespace": "github_codespaces"}},
            ),
            mock.patch(
                "scripts.gar_lib.commands.code.boot_code_codespace",
                return_value=0,
            ) as boot,
        ):
            result = run_code_command("boot", codespace="selected-target")

        self.assertEqual(0, result)
        boot.assert_called_once_with(codespace="selected-target", gh_timeout=None)

    def test_code_command_defaults_to_local_environment(self) -> None:
        with mock.patch(
            "scripts.gar_lib.commands.code.load_config",
            return_value={"selected_providers": {}},
        ), contextlib.redirect_stdout(io.StringIO()) as output:
            result = run_code_command("status")

        self.assertEqual(0, result)
        self.assertIn("Local development environment: available", output.getvalue())

    def test_code_start_writes_codespace_state_and_terminal_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            cwd = home / "workspace"
            cwd.mkdir()
            settings = home / "settings.json"

            def run_side_effect(argv, **kwargs):
                completed = mock.Mock()
                completed.returncode = 0
                completed.stdout = ""
                if argv[:4] == ["gh", "codespace", "ssh", "-c"]:
                    completed.stdout = "Host codespace-host\n  HostName example\n"
                return completed

            with (
                mock.patch("scripts.gar_lib.commands.code.Path.home", return_value=home),
                mock.patch("scripts.gar_lib.commands.code.shutil.which", return_value="/usr/bin/tool"),
                mock.patch("scripts.gar_lib.commands.code.subprocess.run", side_effect=run_side_effect),
            ):
                output = io.StringIO()
                with contextlib.chdir(cwd), contextlib.redirect_stdout(output):
                    result = start_code_codespace(
                        codespace="codespace-test",
                        settings=str(settings),
                        no_mount=True,
                    )

            self.assertEqual(0, result)
            self.assertEqual(
                "Host codespace-host\n  HostName example\n",
                (home / ".ssh" / "codespaces").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "Include ~/.ssh/codespaces",
                (home / ".ssh" / "config").read_text(encoding="utf-8"),
            )
            state = (home / ".config" / "codespace-dev" / "env").read_text(encoding="utf-8")
            self.assertIn("CODESPACE_NAME='codespace-test'", state)
            self.assertIn("CODESPACE_SSH_HOST='codespace-host'", state)
            self.assertIn("CODESPACE_REMOTE_PATH='/workspaces/gar-build-env'", state)
            self.assertIn(f"CODESPACE_MOUNT_DIR='{cwd / 'codespaces'}'", state)
            terminal = home / ".local" / "bin" / "codespace-terminal"
            self.assertIn("Run: gar code start", terminal.read_text(encoding="utf-8"))
            profile = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(
                {"path": str(terminal)},
                profile["terminal.integrated.profiles.linux"]["Codespaces"],
            )

    def test_code_start_times_out_when_gh_ssh_config_hangs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings = home / "settings.json"

            def run_side_effect(argv, **kwargs):
                if argv[:4] == ["gh", "codespace", "ssh", "-c"]:
                    raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
                completed = mock.Mock()
                completed.returncode = 0
                completed.stdout = ""
                return completed

            with (
                mock.patch("scripts.gar_lib.commands.code.Path.home", return_value=home),
                mock.patch("scripts.gar_lib.commands.code.shutil.which", return_value="/usr/bin/tool"),
                mock.patch("scripts.gar_lib.commands.code.subprocess.run", side_effect=run_side_effect),
            ):
                stderr = io.StringIO()
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    result = start_code_codespace(
                        codespace="codespace-test",
                        settings=str(settings),
                        no_mount=True,
                        gh_timeout=3,
                    )

            self.assertEqual(1, result)
            self.assertIn("timed out after 3s", stderr.getvalue())
            self.assertFalse((home / ".ssh" / "codespaces").exists())

    def test_code_start_without_codespace_uses_single_listed_codespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings = home / "settings.json"

            def run_side_effect(argv, **kwargs):
                completed = mock.Mock()
                completed.returncode = 0
                completed.stdout = ""
                if argv == ["gh", "codespace", "list"]:
                    completed.stdout = (
                        "single-codespace\towner/repo\tmain\tStopped\tShutdown\t1h\n"
                    )
                if argv[:4] == ["gh", "codespace", "ssh", "-c"]:
                    completed.stdout = "Host codespace-host\n  HostName example\n"
                return completed

            with (
                mock.patch("scripts.gar_lib.commands.code.Path.home", return_value=home),
                mock.patch("scripts.gar_lib.commands.code.shutil.which", return_value="/usr/bin/tool"),
                mock.patch("scripts.gar_lib.commands.code.subprocess.run", side_effect=run_side_effect) as run,
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = start_code_codespace(settings=str(settings), no_mount=True)

            self.assertEqual(0, result)
            gh_ssh_calls = [
                call.args[0]
                for call in run.call_args_list
                if call.args[0][:4] == ["gh", "codespace", "ssh", "-c"]
            ]
            self.assertEqual(
                ["gh", "codespace", "ssh", "-c", "single-codespace", "--config"],
                gh_ssh_calls[0],
            )

    def test_code_start_detects_workspace_when_default_build_env_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings = home / "settings.json"

            def run_side_effect(argv, **kwargs):
                completed = mock.Mock()
                completed.returncode = 0
                completed.stdout = ""
                if argv[:5] == ["gh", "codespace", "ssh", "-c", "codespace-test"] and argv[-1] == "--config":
                    completed.stdout = "Host codespace-host\n  HostName example\n"
                elif argv[:5] == ["gh", "codespace", "ssh", "-c", "codespace-test"] and "test -d" in argv[-1]:
                    completed.returncode = 1
                elif argv[:5] == ["gh", "codespace", "ssh", "-c", "codespace-test"] and "find /workspaces" in argv[-1]:
                    completed.stdout = "/workspaces/build-hub\n"
                return completed

            with (
                mock.patch("scripts.gar_lib.commands.code.Path.home", return_value=home),
                mock.patch("scripts.gar_lib.commands.code.shutil.which", return_value="/usr/bin/tool"),
                mock.patch("scripts.gar_lib.commands.code.subprocess.run", side_effect=run_side_effect),
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = start_code_codespace(
                        codespace="codespace-test",
                        settings=str(settings),
                        no_mount=True,
                    )

            self.assertEqual(0, result)
            state = (home / ".config" / "codespace-dev" / "env").read_text(encoding="utf-8")
            self.assertIn("CODESPACE_REMOTE_PATH='/workspaces/build-hub'", state)
            self.assertIn("Remote path not found: /workspaces/gar-build-env", output.getvalue())

    def test_code_stop_is_available_from_cli(self) -> None:
        with mock.patch("scripts.gar_lib.cli.run_code_command", return_value=0) as run_code:
            result = main(["code", "stop"])

        self.assertEqual(0, result)
        run_code.assert_called_once_with(
            "stop",
            codespace=None,
            remote_path=None,
            mount_dir=None,
            settings=None,
            profile_name=None,
            no_mount=False,
            shutdown=False,
        )

    def test_code_shutdown_is_available_from_cli(self) -> None:
        with mock.patch("scripts.gar_lib.cli.run_code_command", return_value=0) as run_code:
            result = main(["code", "shutdown", "--codespace", "codespace-test"])

        self.assertEqual(0, result)
        run_code.assert_called_once_with(
            "shutdown",
            codespace="codespace-test",
            remote_path=None,
            mount_dir=None,
            settings=None,
            profile_name=None,
            no_mount=False,
            shutdown=False,
        )

    def test_code_stop_shutdown_flag_is_available_from_cli(self) -> None:
        with mock.patch("scripts.gar_lib.cli.run_code_command", return_value=0) as run_code:
            result = main(["code", "stop", "--shutdown", "--codespace", "codespace-test"])

        self.assertEqual(0, result)
        run_code.assert_called_once_with(
            "stop",
            codespace="codespace-test",
            remote_path=None,
            mount_dir=None,
            settings=None,
            profile_name=None,
            no_mount=False,
            shutdown=True,
        )

    def test_code_stop_unmounts_codespace_and_removes_terminal_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            mount_dir = home / "codespaces" / "gar-build-env"
            mount_dir.mkdir(parents=True)
            state_dir = home / ".config" / "codespace-dev"
            state_dir.mkdir(parents=True)
            (state_dir / "env").write_text(
                "\n".join(
                    [
                        "CODESPACE_SSH_HOST='codespace-host'",
                        "CODESPACE_REMOTE_PATH='/workspaces/gar-build-env'",
                        f"CODESPACE_MOUNT_DIR='{mount_dir}'",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            settings = home / "settings.json"
            settings.write_text(
                json.dumps(
                    {
                        "terminal.integrated.profiles.linux": {
                            "Codespaces": {
                                "path": str(home / ".local" / "bin" / "codespace-terminal")
                            },
                            "bash": {"path": "/bin/bash"},
                        }
                    }
                ),
                encoding="utf-8",
            )

            def run_side_effect(argv, **kwargs):
                completed = mock.Mock()
                completed.returncode = 0
                completed.stdout = ""
                if argv[:4] == ["findmnt", "-n", "-o", "SOURCE"]:
                    completed.stdout = "codespace-host:/workspaces/gar-build-env\n"
                return completed

            with (
                mock.patch("scripts.gar_lib.commands.code.Path.home", return_value=home),
                mock.patch("scripts.gar_lib.commands.code.shutil.which", return_value="/usr/bin/tool"),
                mock.patch("scripts.gar_lib.commands.code.subprocess.run", side_effect=run_side_effect) as run,
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = stop_code_codespace(settings=str(settings))

            self.assertEqual(0, result)
            self.assertIn(
                ["/usr/bin/tool", "-u", str(mount_dir)],
                [call.args[0] for call in run.call_args_list],
            )
            profile = json.loads(settings.read_text(encoding="utf-8"))
            profiles = profile["terminal.integrated.profiles.linux"]
            self.assertNotIn("Codespaces", profiles)
            self.assertIn("bash", profiles)

    def test_code_shutdown_stops_explicit_codespace(self) -> None:
        def run_side_effect(argv, **kwargs):
            completed = mock.Mock()
            completed.returncode = 0
            completed.stdout = ""
            return completed

        with mock.patch("scripts.gar_lib.commands.code.subprocess.run", side_effect=run_side_effect) as run:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = shutdown_code_codespace(codespace="codespace-test")

        self.assertEqual(0, result)
        self.assertIn("Stopping Codespace VM: codespace-test", output.getvalue())
        self.assertEqual(
            ["gh", "codespace", "stop", "-c", "codespace-test"],
            run.call_args_list[0].args[0],
        )

    def test_code_stop_can_shutdown_codespace_from_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            state_dir = home / ".config" / "codespace-dev"
            state_dir.mkdir(parents=True)
            mount_dir = home / "codespaces"
            (state_dir / "env").write_text(
                "\n".join(
                    [
                        "CODESPACE_NAME='codespace-test'",
                        "CODESPACE_SSH_HOST='codespace-host'",
                        "CODESPACE_REMOTE_PATH='/workspaces/gar-build-env'",
                        f"CODESPACE_MOUNT_DIR='{mount_dir}'",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            settings = home / "settings.json"
            settings.write_text("{}", encoding="utf-8")

            def run_side_effect(argv, **kwargs):
                completed = mock.Mock()
                completed.returncode = 0
                completed.stdout = ""
                return completed

            with (
                mock.patch("scripts.gar_lib.commands.code.Path.home", return_value=home),
                mock.patch("scripts.gar_lib.commands.code.shutil.which", return_value="/usr/bin/tool"),
                mock.patch("scripts.gar_lib.commands.code.subprocess.run", side_effect=run_side_effect) as run,
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = stop_code_codespace(settings=str(settings), shutdown=True)

            self.assertEqual(0, result)
            self.assertIn(
                ["gh", "codespace", "stop", "-c", "codespace-test"],
                [call.args[0] for call in run.call_args_list],
            )

    def test_sim_cli_uses_workspace_lifecycle_by_default(self) -> None:
        with mock.patch("scripts.gar_lib.cli.execute_application_command", return_value=0) as run_sim:
            result = main(["sim", "env", "start", "--workspace", "Local/GarStreamTx"])

        self.assertEqual(0, result)
        run_sim.assert_called_once_with(
            SIM_RUNTIME_START,
            workspace_selector="Local/GarStreamTx",
            retry_command="gar sim env start --workspace Local/GarStreamTx",
            settings=None,
            profile_name=None,
            manage_session=True,
        )

    def test_setup_can_store_default_ec2_host(self) -> None:
        config = {"selected_providers": {"simulator": "ssh_remote"}}

        with mock.patch("scripts.gar_lib.commands.setup.save_config") as save_config:
            from scripts.gar_lib.commands.setup import configure_default_ec2_host

            configure_default_ec2_host(config, ec2_host="configured-ec2")

        self.assertEqual("configured-ec2", config["ec2"]["host"])
        save_config.assert_called_once_with(config)

    def test_setup_can_store_esp32_esptool_port(self) -> None:
        class Esp32EsptoolProvider(TargetAccessProvider):
            provider_id = "esp32_esptool"
            display_name = "ESP32 esptool"

        providers = [DevelopmentProvider, Esp32EsptoolProvider]
        targets = [
            TargetManifest(
                id="esp32",
                display_name="ESP32",
                description="target",
                tools_root="targets/esp32",
                default_backends={"codespace": "development_test", "target": "esp32_esptool"},
                backend_notes={},
            ),
        ]
        config = {"selected_target": "esp32", "selected_providers": {"codespace": "development_test", "target": "esp32_esptool"}}

        with (
            mock.patch("scripts.gar_lib.commands.setup.discover_environment_providers", return_value=providers),
            mock.patch("scripts.gar_lib.commands.setup.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.save_config") as save_config,
            mock.patch("scripts.gar_lib.commands.setup.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("sys.stdin.isatty", return_value=False),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_setup(no_install=True, esp32_port="COM3")

        self.assertEqual(0, result)
        self.assertIn("ESP32 Serial Port", output.getvalue())
        self.assertIn("更新しました", output.getvalue())
        save_config.assert_any_call(
            {
                "selected_target": "esp32",
                "selected_providers": {"codespace": "development_test", "target": "esp32_esptool"},
                "esp32": {"port": "COM3"},
            }
        )

    def test_setup_skips_runtime_host_prompt_for_wokwi(self) -> None:
        config = {
            "selected_providers": {"simulator": "wokwi"},
            "ec2": {"host": "not-a-runtime-host"},
        }

        with mock.patch("sys.stdin.isatty", return_value=True), mock.patch("builtins.input") as input_mock:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                from scripts.gar_lib.commands.setup import configure_default_ec2_host

                configure_default_ec2_host(config, ec2_host=None)

        input_mock.assert_not_called()
        self.assertEqual("", output.getvalue())

    def test_load_config_preserves_selected_providers_and_defaults_ec2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / ".gar" / "config.json"
            config_path.parent.mkdir()
            config_path.write_text(
                json.dumps(
                    {
                        "workspaces": [
                            {
                                "id": "ws_test",
                                "name": "product · main",
                                "connection": {"type": "local", "path": str(Path(tmp) / "product")},
                                "branch": "main",
                                "selected_providers": {"codespace": "wsl"},
                                "ec2": {"identity_file": "~/.ssh/test.pem"},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch("scripts.gar_lib.config.CONFIG_PATH", config_path):
                config = load_config()

        self.assertEqual("wsl", config["selected_providers"]["codespace"])
        self.assertEqual("vibecode-graviton", config["ec2"]["host"])
        self.assertEqual("~/.ssh/test.pem", config["ec2"]["identity_file"])

    def test_load_config_selects_workspace_by_setup_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / ".gar" / "config.json"
            config_path.parent.mkdir()
            config_path.write_text(
                json.dumps(
                    {
                        "workspaces": [
                            {
                                "id": "ws_tx",
                                "name": "local/GarStreamTx",
                                "connection": {"type": "local", "path": str(Path(tmp) / "tx")},
                                "branch": "GarStreamTx",
                            },
                            {
                                "id": "ws_rx",
                                "name": "local/GarStreamRx",
                                "connection": {"type": "local", "path": str(Path(tmp) / "rx")},
                                "branch": "GarStreamRx",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch("scripts.gar_lib.config.CONFIG_PATH", config_path),
                mock.patch("scripts.gar_lib.config._ACTIVE_WORKSPACE_ROOT", "local/GarStreamRx"),
            ):
                config = load_config()

        self.assertEqual("ws_rx", config["workspace_id"])
        self.assertEqual("GarStreamRx", config["workspace_branch"])

    def test_default_workspace_name_has_no_spaces(self) -> None:
        from scripts.gar_lib.commands.setup import default_workspace_name, default_workspace_product_name

        self.assertEqual("Local/GarStreamTx", default_workspace_name("local", "GarStreamTx"))
        self.assertEqual("Codespaces/GarStreamTx", default_workspace_name("codespaces", "GarStreamTx"))
        self.assertEqual("Network/GarStreamTx", default_workspace_name("network", "GarStreamTx"))
        self.assertEqual(
            "GarStreamTx",
            default_workspace_product_name("GarStreamTx", "/home/user/Yurufuwa/GarStreamTx"),
        )
        self.assertEqual(
            "GarVibeRemote",
            default_workspace_product_name("main", "/home/user/Yurufuwa/GarVibeRemote"),
        )

    def test_load_config_ignores_legacy_top_level_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / ".gar" / "config.json"
            config_path.parent.mkdir()
            config_path.write_text(
                json.dumps(
                    {
                        "selected_providers": {"codespace": "wsl"},
                        "selected_target": "esp32",
                        "workspace": {"roots": ["/legacy"]},
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch("scripts.gar_lib.config.CONFIG_PATH", config_path),
                mock.patch("scripts.gar_lib.config._ACTIVE_WORKSPACE_ROOT", None),
            ):
                config = load_config()

        self.assertEqual([], config["workspaces"])
        self.assertEqual({}, config["selected_providers"])
        self.assertNotIn("selected_target", config)

    def test_discover_target_manifests_reads_gar_tools_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_dir = Path(tmp) / "esp32"
            target_dir.mkdir()
            (target_dir / "target.json").write_text(
                json.dumps(
                    {
                        "id": "esp32",
                        "displayName": "ESP32",
                        "description": "test target",
                        "toolsRoot": "targets/esp32",
                        "defaultBackends": {"simulator": "wokwi"},
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {"GAR_TOOLS_TARGETS": tmp}):
                targets = discover_target_manifests()

        self.assertEqual(1, len(targets))
        self.assertEqual("esp32", targets[0].id)
        self.assertEqual({"simulator": "wokwi"}, targets[0].default_backends)

    def test_discover_target_manifests_reads_gar_tools_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "gar-tools"
            target_dir = root / "targets" / "linux-device"
            target_dir.mkdir(parents=True)
            (target_dir / "target.json").write_text(
                json.dumps(
                    {
                        "id": "linux-device",
                        "displayName": "Linux Device",
                        "description": "test target",
                        "toolsRoot": "targets/linux-device",
                        "defaultBackends": {"simulator": "ssh_remote"},
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {"GAR_TOOLS_ROOT": str(root)}):
                targets = discover_target_manifests()

        self.assertEqual(1, len(targets))
        self.assertEqual("linux-device", targets[0].id)

    def test_ensure_gar_tools_available_clones_into_gar_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "GaplessAgentRuntime"
            project_root.mkdir()
            completed = subprocess.CompletedProcess(["git"], 0)
            with (
                mock.patch("scripts.gar_lib.gar_tools.PROJECT_ROOT", project_root),
                mock.patch.dict(os.environ, {"GAR_TOOLS_REPO": "https://example.invalid/gar-tools"}, clear=True),
                mock.patch("scripts.gar_lib.gar_tools.subprocess.run", return_value=completed) as run,
            ):
                root = ensure_gar_tools_available()

        self.assertEqual(project_root / ".gar" / "tools", root)
        run.assert_called_once_with(
            ["git", "clone", "--depth", "1", "https://example.invalid/gar-tools", str(project_root / ".gar" / "tools")],
            check=False,
        )

    def test_load_config_warns_on_invalid_json(self) -> None:
        from scripts.gar_lib.config import default_config

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / ".gar" / "config.json"
            config_path.parent.mkdir()
            config_path.write_text("{ not json", encoding="utf-8")

            stderr = io.StringIO()
            with (
                mock.patch("scripts.gar_lib.config.CONFIG_PATH", config_path),
                contextlib.redirect_stderr(stderr),
            ):
                config = load_config()

        self.assertEqual(default_config(), config)
        self.assertIn("not valid JSON", stderr.getvalue())

    def test_default_config_leaves_target_unselected(self) -> None:
        from scripts.gar_lib.config import default_config

        config = default_config()

        self.assertNotIn("selected_target", config)
        self.assertEqual({}, config["selected_providers"])
        self.assertNotIn("instance_id", config["ec2"])
        self.assertNotIn("region", config["ec2"])

    def test_save_config_is_atomic_and_leaves_no_temp_file(self) -> None:
        from scripts.gar_lib.config import save_config

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / ".gar" / "config.json"
            workspace_path = str(Path(tmp) / "product")

            with mock.patch("scripts.gar_lib.config.CONFIG_PATH", config_path):
                save_config(
                    {
                        "workspace_id": "ws_test",
                        "workspace_name": "product · main",
                        "workspace_connection": {"type": "local", "path": workspace_path},
                        "workspace_branch": "main",
                        "workspaces": [
                            {
                                "id": "ws_test",
                                "name": "product · main",
                                "connection": {"type": "local", "path": workspace_path},
                                "branch": "main",
                            }
                        ],
                        "selected_providers": {"target": "ssh_scp"},
                    }
                )

            self.assertTrue(config_path.is_file())
            data = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual({"target": "ssh_scp"}, data["workspaces"][0]["selected_providers"])

            leftovers = [
                path
                for path in config_path.parent.iterdir()
                if path.name != config_path.name
            ]
            self.assertEqual([], leftovers)

    def test_project_root_points_to_repository_root(self) -> None:
        """PROJECT_ROOT must resolve to the repo root, not scripts/."""
        from scripts.gar_lib.config import PROJECT_ROOT

        self.assertTrue(
            (PROJECT_ROOT / "AGENT.md").is_file(),
            f"PROJECT_ROOT={PROJECT_ROOT} is not the repository root "
            "(AGENT.md not found at expected location).",
        )
        self.assertTrue((PROJECT_ROOT / "scripts" / "gar_lib").is_dir())

    def test_terminal_gc_removes_old_processed_requests(self) -> None:
        from scripts.gar_lib.commands.terminal import run_terminal_gc

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            processed = tmp_path / ".gar" / "terminal-requests" / "processed"
            status_dir = tmp_path / ".gar" / "terminal-status"
            processed.mkdir(parents=True)
            status_dir.mkdir(parents=True)

            old = processed / "old.started.json"
            new = processed / "new.started.json"
            old_status = status_dir / "old.json"
            old.write_text("{}", encoding="utf-8")
            new.write_text("{}", encoding="utf-8")
            old_status.write_text("{}", encoding="utf-8")

            old_mtime = datetime.now(UTC).timestamp() - 30 * 86400
            os.utime(old, (old_mtime, old_mtime))
            os.utime(old_status, (old_mtime, old_mtime))

            with (
                mock.patch(
                    "scripts.gar_lib.commands.terminal.CONFIG_PATH",
                    tmp_path / ".gar" / "config.json",
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = run_terminal_gc(keep_days=7, dry_run=False)

            self.assertEqual(0, result)
            self.assertFalse(old.exists())
            self.assertFalse(old_status.exists())
            self.assertTrue(new.exists())

    def test_parse_sim_diag_builds_structured_payload(self) -> None:
        raw = (
            "@@PROC@@\n"
            "1234 /usr/bin/python3 /home/ubuntu/web-bridge/bridge.py\n"
            "1235 ./cuse_i2c -f --devname=i2c-1\n"
            "@@DEV@@\n"
            "/dev/i2c-1 1\n"
            "/dev/gpiochip0 0\n"
            "/dev/spidev0.0 0\n"
            "@@API@@\n"
            '{"led18": 1, "button17": 0}\n'
        )
        payload = parse_sim_diag(raw)

        self.assertEqual(2, len(payload["processes"]))
        self.assertEqual(1234, payload["processes"][0]["pid"])
        self.assertIn("bridge.py", payload["processes"][0]["cmd"])
        self.assertEqual(
            {"/dev/i2c-1": True, "/dev/gpiochip0": False, "/dev/spidev0.0": False},
            payload["devices"],
        )
        self.assertEqual({"led18": 1, "button17": 0}, payload["api"])
        self.assertTrue(payload["ok"])

    def test_parse_sim_diag_marks_not_ok_when_api_missing(self) -> None:
        raw = (
            "@@PROC@@\n"
            "@@DEV@@\n"
            "/dev/i2c-1 0\n"
            "@@API@@\n"
        )
        payload = parse_sim_diag(raw)

        self.assertEqual([], payload["processes"])
        self.assertIsNone(payload["api"])
        self.assertFalse(payload["ok"])

    def test_parse_gpio_sim_check_builds_structured_payload(self) -> None:
        raw = (
            "@@KERNEL@@\n"
            "6.8.0-test\n"
            "@@MODINFO@@\n"
            "1\n"
            "filename: /lib/modules/gpio-sim.ko\n"
            "@@CONFIG@@\n"
            "CONFIG_GPIO_SIM=m\n"
            "@@CONFIGFS@@\n"
            "1\n"
            "@@DEV@@\n"
            "/dev/gpiochip0\n"
        )
        payload = parse_gpio_sim_check(raw)

        self.assertEqual("6.8.0-test", payload["kernel"])
        self.assertTrue(payload["module_available"])
        self.assertTrue(payload["config_mentions_gpio_sim"])
        self.assertTrue(payload["configfs_available"])
        self.assertEqual(["/dev/gpiochip0"], payload["gpiochips"])
        self.assertTrue(payload["ok"])

    def test_parse_gpio_runtime_status_builds_structured_payload(self) -> None:
        raw = (
            "@@SERVICE@@\n"
            "active\n"
            "@@DEVICE@@\n"
            "/dev/gpiochip0 1\n"
            "@@MOUNT@@\n"
            "1\n"
            "/dev/gpiochip1\n"
            "@@CONFIGFS@@\n"
            "1\n"
            "1\n"
            "gpiochip1\n"
            "@@GPIOCHIPS@@\n"
            "/dev/gpiochip0\n"
            "/dev/gpiochip1\n"
        )

        payload = parse_gpio_runtime_status(raw)

        self.assertEqual("active", payload["service"])
        self.assertEqual({"path": "/dev/gpiochip0", "exists": True}, payload["device"])
        self.assertEqual({"active": True, "source": "/dev/gpiochip1"}, payload["mount"])
        self.assertEqual(
            {"active": True, "live": "1", "chip_name": "gpiochip1"},
            payload["configfs"],
        )
        self.assertTrue(payload["ok"])

    def test_sim_env_gpio_start_is_available_from_cli(self) -> None:
        with mock.patch("scripts.gar_lib.cli.execute_application_command", return_value=0) as run_gpio:
            result = main(
                ["sim", "env", "gpio", "start", "--workspace", "Network/Product"]
            )

        self.assertEqual(0, result)
        run_gpio.assert_called_once_with(
            GarCommand("sim", "gpio", "start"),
            workspace_selector="Network/Product",
            retry_command="gar sim env gpio start --workspace Network/Product",
            json_output=False,
        )

    def test_sim_env_gpio_plan_json_is_available_from_cli(self) -> None:
        with mock.patch("scripts.gar_lib.cli.execute_application_command", return_value=0) as run_gpio:
            result = main(["sim", "env", "gpio", "plan", "--json"])

        self.assertEqual(0, result)
        run_gpio.assert_called_once_with(
            GarCommand("sim", "gpio", "plan"),
            workspace_selector=None,
            retry_command="gar sim env gpio plan",
            json_output=True,
        )

    def test_sim_diag_json_without_explicit_host_uses_workspace_environment(self) -> None:
        with mock.patch("scripts.gar_lib.cli.execute_application_command", return_value=0) as run_diag:
            result = main(
                ["sim", "env", "diag", "--json", "--workspace", "Local/GarStreamTx"]
            )

        self.assertEqual(0, result)
        run_diag.assert_called_once_with(
            SIM_RUNTIME_DIAG,
            workspace_selector="Local/GarStreamTx",
            retry_command="gar sim env diag --json --workspace Local/GarStreamTx",
            json_output=True,
        )


class SimPanelTests(unittest.TestCase):
    def test_build_panel_command_button_press(self) -> None:
        command = LinuxSystemdCommandBuilder().build_panel("button-press", {"button": "17", "duration_ms": 150})
        self.assertIn("/api/button/press?line=17&duration_ms=150", command)
        self.assertIn("-X POST", command)

    def test_build_panel_command_button_press_accepts_name(self) -> None:
        command = LinuxSystemdCommandBuilder().build_panel("button-press", {"button": "A", "duration_ms": 150})
        self.assertIn("/api/button/press?line=17&duration_ms=150", command)

    def test_build_panel_command_rfid_tap_encodes_uid(self) -> None:
        command = LinuxSystemdCommandBuilder().build_panel("rfid-tap", {"uid": "04:AB:CD:EF:01:23"})
        self.assertIn("/api/rfid/tap?uid=04:AB:CD:EF:01:23", command)

    def test_build_panel_command_state_is_get(self) -> None:
        command = LinuxSystemdCommandBuilder().build_panel("state", {})
        self.assertIn("/api/state", command)
        self.assertNotIn("-X POST", command)

    def test_build_panel_command_rejects_unknown_action(self) -> None:
        with self.assertRaises(ValueError):
            LinuxSystemdCommandBuilder().build_panel("explode", {})

    def test_sim_ui_is_not_a_public_cli_command(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as exc:
                main(["sim", "ui", "button", "press", "17"])

        self.assertEqual(2, exc.exception.code)
        self.assertIn("invalid choice: 'ui'", stderr.getvalue())

    def test_hw_init_copies_gar_tools_csv_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools_hw = root / "gar-tools" / "targets" / "linux-device" / "hardware"
            tools_hw.mkdir(parents=True)
            templates = {
                "components.csv": "component_id,name,kind,part_number,description\nboard,Board,board,Test,Template row\n",
                "gpio.csv": "name,chip,line,direction,role,active,initial,pull,sim_control,description\nbutton,/dev/gpiochip0,1,input,button,high,,pull-up,pull,Template row\n",
                "i2c.csv": "name,bus,dev,address,driver,sim,description\noled,1,/dev/i2c-1,0x3c,ssd1306,ssd1306,Template row\n",
                "spi.csv": "name,bus,chip_select,dev,mode,max_speed_hz,driver,sim,description\nrfid,0,0,/dev/spidev0.0,0,1000000,mfrc522,mfrc522,Template row\n",
                "connections.csv": "source,source_pin,target,target_pin,signal,description\nboard,GPIO1,button,signal,GPIO1,Template row\n",
            }
            for name, content in templates.items():
                (tools_hw / name).write_text(content, encoding="utf-8")

            hw_dir = root / "hardware"
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"GAR_TOOLS_ROOT": str(root / "gar-tools")}),
                contextlib.redirect_stdout(output),
            ):
                result = main(["hw", "init", "--dir", str(hw_dir)])

            self.assertEqual(0, result)
            for name, content in templates.items():
                self.assertEqual(content, (hw_dir / name).read_text(encoding="utf-8"))

    def test_hw_init_refuses_to_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hw_dir = Path(tmp) / "hardware"
            hw_dir.mkdir()
            gpio_csv = hw_dir / "gpio.csv"
            gpio_csv.write_text("keep me\n", encoding="utf-8")

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(["hw", "init", "--dir", str(hw_dir)])

            self.assertEqual(1, result)
            self.assertEqual("keep me\n", gpio_csv.read_text(encoding="utf-8"))
            self.assertIn("--force", output.getvalue())

    def test_hw_init_is_available_from_cli(self) -> None:
        with mock.patch("scripts.gar_lib.cli.run_hw_command", return_value=0) as run_hw:
            result = main(["hw", "init", "--dir", "custom-hw", "--force"])

        self.assertEqual(0, result)
        run_hw.assert_called_once_with(
            "init",
            output_dir="custom-hw",
            force=True,
        )


if __name__ == "__main__":
    unittest.main()
