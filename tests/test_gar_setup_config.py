import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support.gar_cli_test_support import (
    FakeDevelopmentEnvironment,
    FakeMissingSimulationEnvironment,
    FakeMissingTargetAccessEnvironment,
    FakeSimulationEnvironment,
    FakeTargetAccessEnvironment,
    FakeWokwiEnvironment,
)

from scripts.gar_lib.commands.setup import run_setup
from scripts.gar_lib.commands.setup.command import _configure_selected_environment_connection
from scripts.gar_lib.commands.setup.simulation_host_setup import configure_simulation_host_connection
from scripts.gar_lib.commands.workspace_resolver import resolve_workspace
from scripts.gar_lib.core.config import load_config, save_config
from scripts.gar_lib.core.tools_repository import ensure_gar_tools_available
from scripts.gar_lib.environments.setup_option import SimulationHostSetupOption
from scripts.gar_lib.target.manifest import TargetManifest, discover_target_manifests


class GarSetupConfigTest(unittest.TestCase):
    def test_switching_sim_host_provider_clears_previous_provider_bindings(self) -> None:
        config = {
            "selected_environments": {"simulation_host": "virtualbox"},
            "simulation_host": {
                "provider": "aws_ec2",
                "host": "stale-aws",
                "private_ip": "10.0.0.10",
                "arch": "aarch64",
            },
        }

        with (
            mock.patch("scripts.gar_lib.commands.setup.simulation_host_setup.save_config") as save_config,
            mock.patch("scripts.gar_lib.commands.setup.simulation_host_setup.sys.stdin.isatty", return_value=False),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            configure_simulation_host_connection(config)

        self.assertEqual({"provider": "virtualbox"}, config["simulation_host"])
        save_config.assert_called_once_with(config)

    def test_selecting_ssh_simulation_defers_connection_to_sim_host_category(self) -> None:
        config = {"selected_environments": {"simulator": "ssh_remote"}}
        with (
            mock.patch("scripts.gar_lib.commands.setup.command.configure_simulation_host_connection") as configure_host,
            mock.patch("scripts.gar_lib.commands.setup.command.configure_target_connection") as configure_target,
        ):
            _configure_selected_environment_connection("simulator", "ssh_remote", config, ec2_host=None)

        configure_host.assert_not_called()
        configure_target.assert_not_called()

    def test_selecting_simulation_host_prompts_for_provider_connection(self) -> None:
        config = {"selected_environments": {"simulation_host": "virtualbox"}}
        with mock.patch(
            "scripts.gar_lib.commands.setup.command.configure_simulation_host_connection"
        ) as configure_host:
            _configure_selected_environment_connection(
                "simulation_host",
                "virtualbox",
                config,
                ec2_host=None,
            )

        configure_host.assert_called_once_with(config, ec2_host=None)

    def test_selecting_ssh_target_prompts_for_its_host_immediately(self) -> None:
        config = {"selected_environments": {"target": "ssh_scp"}}
        with (
            mock.patch("scripts.gar_lib.commands.setup.command.configure_simulation_host_connection") as configure_host,
            mock.patch("scripts.gar_lib.commands.setup.command.configure_target_connection") as configure_target,
        ):
            _configure_selected_environment_connection("target", "ssh_scp", config, ec2_host=None)

        configure_host.assert_not_called()
        configure_target.assert_called_once_with(config)

    def test_setup_lists_only_selected_environment_for_configured_category(self) -> None:
        environments = [FakeDevelopmentEnvironment, FakeSimulationEnvironment, FakeTargetAccessEnvironment]
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
            "selected_environments": {
                "codespace": "development_test",
                "simulator": "simulation_test",
                "target": "device_test",
            },
        }

        with (
            mock.patch("scripts.gar_lib.commands.setup.command.discover_environments", return_value=environments),
            mock.patch("scripts.gar_lib.commands.setup.command.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.command.load_config", return_value=config),
            mock.patch(
                "scripts.gar_lib.commands.setup.command.installed_vscode_terminal_bridge_path", return_value=None
            ),
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
        self.assertIn("設定が完了しました。", text)

    def test_setup_defaults_to_first_unconfigured_category_environment(self) -> None:
        environments = [FakeDevelopmentEnvironment, FakeMissingTargetAccessEnvironment]
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
            "selected_environments": {"codespace": "development_test"},
        }

        with (
            mock.patch("scripts.gar_lib.commands.setup.command.discover_environments", return_value=environments),
            mock.patch("scripts.gar_lib.commands.setup.command.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.command.load_config", return_value=config),
            mock.patch(
                "scripts.gar_lib.commands.setup.command.installed_vscode_terminal_bridge_path", return_value=None
            ),
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
        self.assertIn("未完了の設定", text)

    def test_setup_saves_selected_environment_after_successful_setup(self) -> None:
        environments = [FakeDevelopmentEnvironment]
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
        config = {"selected_target": "test-target", "selected_environments": {}}

        with (
            mock.patch("scripts.gar_lib.commands.setup.command.discover_environments", return_value=environments),
            mock.patch("scripts.gar_lib.commands.setup.command.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.command.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.command.save_config") as save_config,
            mock.patch(
                "scripts.gar_lib.commands.setup.command.installed_vscode_terminal_bridge_path", return_value=None
            ),
            mock.patch("builtins.input", side_effect=["", "", "", "q"]),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_setup(no_install=True)

        self.assertEqual(0, result)
        save_config.assert_called_once_with(
            {"selected_target": "test-target", "selected_environments": {"codespace": "development_test"}}
        )

    def test_environment_dependency_success_message_names_environment(self) -> None:
        from scripts.gar_lib.commands.setup import ensure_environment_dependencies

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = ensure_environment_dependencies(FakeDevelopmentEnvironment, no_install=True)

        self.assertEqual(0, result)
        self.assertIn("Development Test に必要なコマンドは見つかりました。", output.getvalue())
        self.assertNotIn("必要なコマンドはすべて見つかりました。", output.getvalue())

    def test_setup_saves_selected_target_when_interactive(self) -> None:
        environments = [FakeDevelopmentEnvironment, FakeWokwiEnvironment, FakeTargetAccessEnvironment]
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
        config = {"selected_environments": {"codespace": "development_test"}}

        with (
            mock.patch("scripts.gar_lib.commands.setup.command.discover_environments", return_value=environments),
            mock.patch("scripts.gar_lib.commands.setup.command.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.command.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.command.save_config"),
            mock.patch("scripts.gar_lib.commands.setup.target_setup.save_config") as save_target_config,
            mock.patch("scripts.gar_lib.commands.setup.command.configure_default_ec2_host"),
            mock.patch(
                "scripts.gar_lib.commands.setup.command.installed_vscode_terminal_bridge_path", return_value=None
            ),
            mock.patch("sys.stdin.isatty", return_value=True),
            mock.patch("builtins.input", side_effect=["", "1", "2", "", "", "q"]),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_setup(no_install=True)

        self.assertEqual(0, result)
        save_target_config.assert_any_call(
            {"selected_target": "esp32", "selected_environments": {"codespace": "development_test"}}
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
        environments = [FakeDevelopmentEnvironment]
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
        config = {"selected_environments": {}}

        with (
            mock.patch("scripts.gar_lib.commands.setup.command.discover_environments", return_value=environments),
            mock.patch("scripts.gar_lib.commands.setup.command.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.command.load_config", return_value=config),
            mock.patch(
                "scripts.gar_lib.commands.setup.command.installed_vscode_terminal_bridge_path", return_value=None
            ),
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
        environments = [FakeDevelopmentEnvironment, FakeWokwiEnvironment]
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
            "selected_environments": {"codespace": "development_test"},
        }

        with (
            mock.patch("scripts.gar_lib.commands.setup.command.discover_environments", return_value=environments),
            mock.patch("scripts.gar_lib.commands.setup.command.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.command.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.target_setup.save_config") as save_config,
            mock.patch(
                "scripts.gar_lib.commands.setup.command.installed_vscode_terminal_bridge_path", return_value=None
            ),
            mock.patch("sys.stdin.isatty", return_value=False),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_setup(no_install=True)

        self.assertEqual(0, result)
        save_config.assert_not_called()

    def test_setup_wokwi_flow_explains_required_and_optional_steps(self) -> None:
        environments = [FakeDevelopmentEnvironment, FakeWokwiEnvironment, FakeMissingTargetAccessEnvironment]
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
            "selected_environments": {"codespace": "development_test", "simulator": "wokwi", "target": "missing_test"},
        }

        with (
            mock.patch("scripts.gar_lib.commands.setup.command.discover_environments", return_value=environments),
            mock.patch("scripts.gar_lib.commands.setup.command.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.command.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.target_setup.save_config"),
            mock.patch(
                "scripts.gar_lib.commands.setup.command.installed_vscode_terminal_bridge_path", return_value=None
            ),
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
        self.assertIn("scripts/gar sim build app", text)
        self.assertIn("scripts/gar sim deploy app", text)
        self.assertIn("product-sim-build hook", text)
        self.assertIn("scripts/gar sim start --no-port-forward", text)
        self.assertIn("scripts/gar sim diag --json", text)
        self.assertNotIn("scripts/gar sim build runtime", text)
        self.assertNotIn("make wokwi-workspace", text)
        self.assertIn("人間がUIを確認", text)
        self.assertIn("シミュレート環境", text)
        self.assertIn("実機環境", text)
        self.assertIn("後で設定可", text)
        self.assertIn("あとで設定できる項目", text)
        self.assertNotIn("未完了の設定", text)

    def test_setup_allows_simulation_to_remain_unconfigured(self) -> None:
        environments = [FakeDevelopmentEnvironment, FakeMissingSimulationEnvironment]
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
            "selected_environments": {
                "codespace": "development_test",
                "simulator": "missing_simulation",
            },
        }

        with (
            mock.patch("scripts.gar_lib.commands.setup.command.discover_environments", return_value=environments),
            mock.patch("scripts.gar_lib.commands.setup.command.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.command.load_config", return_value=config),
            mock.patch(
                "scripts.gar_lib.commands.setup.command.installed_vscode_terminal_bridge_path", return_value=None
            ),
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
        self.assertNotIn("未完了の設定", text)

    def test_setup_defaults_to_optional_category_after_required_items(self) -> None:
        from scripts.gar_lib.commands.setup import (
            EnvironmentCategory,
            first_unconfigured_category_index,
        )

        categories = [
            EnvironmentCategory("codespace", "開発環境", (FakeDevelopmentEnvironment,)),
            EnvironmentCategory("simulator", "シミュレート環境", (FakeWokwiEnvironment,)),
            EnvironmentCategory("target", "実機環境", (FakeMissingTargetAccessEnvironment,)),
        ]
        config = {
            "selected_environments": {
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
        environments = [FakeDevelopmentEnvironment, FakeWokwiEnvironment, FakeTargetAccessEnvironment]
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
                default_backends={
                    "codespace": "development_test",
                    "simulator": "simulation_test",
                    "target": "device_test",
                },
                backend_notes={},
            ),
        ]
        config = {
            "selected_target": "esp32",
            "selected_environments": {
                "codespace": "development_test",
                "simulator": "wokwi",
                "target": "device_test",
                "boot": "esp32_qemu_firmware",
                "hostLink": "fake-idf",
                "probe": "spp-jsonl",
            },
        }

        with (
            mock.patch("scripts.gar_lib.commands.setup.command.discover_environments", return_value=environments),
            mock.patch("scripts.gar_lib.commands.setup.command.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.command.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.target_setup.save_config") as save_config,
            mock.patch("scripts.gar_lib.commands.setup.command.configure_default_ec2_host"),
            mock.patch(
                "scripts.gar_lib.commands.setup.command.installed_vscode_terminal_bridge_path", return_value=None
            ),
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
                "selected_environments": {
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
        environments = [FakeDevelopmentEnvironment, FakeSimulationEnvironment]
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
            "selected_environments": {
                "codespace": "development_test",
                "simulator": "simulation_test",
            },
        }

        with (
            mock.patch("scripts.gar_lib.commands.setup.command.discover_environments", return_value=environments),
            mock.patch("scripts.gar_lib.commands.setup.command.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.command.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.command.configure_default_ec2_host"),
            mock.patch(
                "scripts.gar_lib.commands.setup.command.installed_vscode_terminal_bridge_path", return_value=None
            ),
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
        environments = [FakeDevelopmentEnvironment, FakeWokwiEnvironment, FakeTargetAccessEnvironment]
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
            "selected_environments": {
                "codespace": "development_test",
                "simulator": "wokwi",
                "target": "device_test",
                "boot": "esp32_qemu_firmware",
                "hostLink": "fake-idf",
                "probe": "spp-jsonl",
            },
        }

        with (
            mock.patch("scripts.gar_lib.commands.setup.command.discover_environments", return_value=environments),
            mock.patch("scripts.gar_lib.commands.setup.command.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.command.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.target_setup.save_config") as save_config,
            mock.patch(
                "scripts.gar_lib.commands.setup.command.installed_vscode_terminal_bridge_path", return_value=None
            ),
            mock.patch("sys.stdin.isatty", return_value=False),
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                result = run_setup(no_install=True)

        self.assertEqual(0, result)
        save_config.assert_called_once_with(
            {
                "selected_target": "esp32",
                "selected_environments": {
                    "codespace": "development_test",
                    "simulator": "wokwi",
                    "target": "device_test",
                },
            }
        )

    def test_setup_environment_selection_accepts_quit(self) -> None:
        environments = [FakeDevelopmentEnvironment]
        config = {"selected_environments": {}}

        with (
            mock.patch("scripts.gar_lib.commands.setup.command.discover_environments", return_value=environments),
            mock.patch("scripts.gar_lib.commands.setup.command.discover_target_manifests", return_value=[]),
            mock.patch("scripts.gar_lib.commands.setup.command.load_config", return_value=config),
            mock.patch(
                "scripts.gar_lib.commands.setup.command.installed_vscode_terminal_bridge_path", return_value=None
            ),
            mock.patch("builtins.input", side_effect=["", "q"]),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_setup(no_install=True)

        self.assertEqual(1, result)
        self.assertIn("未完了の設定", output.getvalue())

    def test_setup_can_store_default_ec2_host(self) -> None:
        config = {"selected_environments": {"simulator": "ssh_remote"}}

        with mock.patch("scripts.gar_lib.commands.setup.environment_setup.save_config") as save_config:
            from scripts.gar_lib.commands.setup import configure_default_ec2_host

            configure_default_ec2_host(config, ec2_host="configured-ec2")

        self.assertEqual("configured-ec2", config["ec2"]["host"])
        save_config.assert_called_once_with(config)

    def test_setup_rejects_invalid_explicit_ec2_host_before_saving(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            result = run_setup(no_install=True, ec2_host="host with spaces")

        self.assertEqual(1, result)
        self.assertIn("--ec2-host", stderr.getvalue())

    def test_setup_reports_missing_host_for_ssh_simulation(self) -> None:
        class FakeSshSimulationEnvironment(FakeSimulationEnvironment):
            environment_id = "ssh_remote"

        class FakeAwsSimulationHost(SimulationHostSetupOption):
            environment_id = "aws_ec2"
            display_name = "AWS"
            description = "AWS Sim Host"
            required_commands = ()

        environments = [
            FakeDevelopmentEnvironment,
            FakeSshSimulationEnvironment,
            FakeAwsSimulationHost,
            FakeTargetAccessEnvironment,
        ]
        targets = [
            TargetManifest(
                id="ssh-target",
                display_name="SSH Target",
                description="target",
                tools_root="targets/ssh-target",
                default_backends={
                    "codespace": "development_test",
                    "simulator": "ssh_remote",
                    "target": "device_test",
                },
                backend_notes={},
            )
        ]
        config = {
            "selected_target": "ssh-target",
            "selected_environments": {
                "codespace": "development_test",
                "simulator": "ssh_remote",
                "simulation_host": "aws_ec2",
                "target": "device_test",
            },
        }

        with (
            mock.patch(
                "scripts.gar_lib.commands.setup.command.discover_environments",
                return_value=environments,
            ),
            mock.patch(
                "scripts.gar_lib.commands.setup.command.discover_target_manifests",
                return_value=targets,
            ),
            mock.patch(
                "scripts.gar_lib.commands.setup.command.load_config",
                return_value=config,
            ),
            mock.patch("sys.stdin.isatty", return_value=False),
            mock.patch("builtins.input", side_effect=EOFError),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            result = run_setup(no_install=True)

        self.assertEqual(1, result)
        self.assertIn("Remote Sim Host (--ec2-host)", stdout.getvalue())

    def test_setup_can_store_esp32_esptool_port(self) -> None:
        class FakeEsp32EsptoolEnvironment(FakeTargetAccessEnvironment):
            environment_id = "esp32_esptool"
            display_name = "ESP32 esptool"

        environments = [FakeDevelopmentEnvironment, FakeEsp32EsptoolEnvironment]
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
        config = {
            "selected_target": "esp32",
            "selected_environments": {"codespace": "development_test", "target": "esp32_esptool"},
        }

        with (
            mock.patch("scripts.gar_lib.commands.setup.command.discover_environments", return_value=environments),
            mock.patch("scripts.gar_lib.commands.setup.command.discover_target_manifests", return_value=targets),
            mock.patch("scripts.gar_lib.commands.setup.command.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.target_setup.save_config") as save_config,
            mock.patch(
                "scripts.gar_lib.commands.setup.command.installed_vscode_terminal_bridge_path", return_value=None
            ),
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
                "selected_environments": {"codespace": "development_test", "target": "esp32_esptool"},
                "esp32": {"port": "COM3"},
            }
        )

    def test_setup_skips_runtime_host_prompt_for_wokwi(self) -> None:
        config = {
            "selected_environments": {"simulator": "wokwi"},
            "ec2": {"host": "not-a-runtime-host"},
        }

        with mock.patch("sys.stdin.isatty", return_value=True), mock.patch("builtins.input") as input_mock:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                from scripts.gar_lib.commands.setup import configure_default_ec2_host

                configure_default_ec2_host(config, ec2_host=None)

        input_mock.assert_not_called()
        self.assertEqual("", output.getvalue())

    def test_load_config_preserves_selected_environments_without_guessing_ec2_host(self) -> None:
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
                                "selected_environments": {"codespace": "wsl"},
                                "ec2": {"identity_file": "~/.ssh/test.pem"},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch("scripts.gar_lib.core.config.CONFIG_PATH", config_path):
                config = load_config()

        self.assertEqual("wsl", config["selected_environments"]["codespace"])
        self.assertNotIn("host", config["ec2"])
        self.assertEqual("~/.ssh/test.pem", config["ec2"]["identity_file"])

    def test_load_config_accepts_legacy_selected_providers_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / ".gar" / "config.json"
            config_path.parent.mkdir()
            entry = {
                "id": "ws_test",
                "name": "product · main",
                "connection": {"type": "local", "path": str(Path(tmp) / "product")},
                "branch": "main",
                "selected_providers": {"codespace": "local", "simulator": "local_docker"},
                "selected_target": "linux-device",
                "hardware": {"path": "config/hardware"},
            }
            config_path.write_text(json.dumps({"workspaces": [entry]}), encoding="utf-8")

            with mock.patch("scripts.gar_lib.core.config.CONFIG_PATH", config_path):
                config = load_config()
                save_config(config)
                migrated = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual("local", config["selected_environments"]["codespace"])
        self.assertEqual("local_docker", config["selected_environments"]["simulator"])
        self.assertEqual(
            {"codespace": "local", "simulator": "local_docker"},
            migrated["workspaces"][0]["selected_environments"],
        )
        self.assertNotIn("selected_providers", migrated["workspaces"][0])
        self.assertEqual("linux-device", migrated["workspaces"][0]["selected_target"])
        self.assertEqual(
            {"path": "config/hardware"},
            migrated["workspaces"][0]["hardware"],
        )

    def test_load_and_save_preserves_build_and_simulation_provider_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / ".gar" / "config.json"
            config_path.parent.mkdir()
            entry = {
                "id": "ws_test",
                "name": "Local/Product",
                "connection": {"type": "local", "path": str(Path(tmp) / "product")},
                "branch": "main",
                "selected_environments": {
                    "codespace": "local",
                    "simulator": "ssh_remote",
                    "simulation_host": "virtualbox",
                },
                "build": {"image": "custom-build:latest", "docker_socket": True},
                "simulation_host": {
                    "provider": "virtualbox",
                    "host": "gar-sim-local",
                    "arch": "x86_64",
                },
                "virtualbox": {"vm": "GAR Ubuntu Sim"},
                "docker": {"image": "legacy-sim:latest", "arch": "x86_64"},
                "ec2": {"host": "legacy-aws", "arch": "aarch64"},
            }
            config_path.write_text(json.dumps({"workspaces": [entry]}), encoding="utf-8")

            with mock.patch("scripts.gar_lib.core.config.CONFIG_PATH", config_path):
                config = load_config()
                save_config(config)
                saved = json.loads(config_path.read_text(encoding="utf-8"))["workspaces"][0]

        self.assertEqual(entry["build"], saved["build"])
        self.assertEqual(entry["simulation_host"], saved["simulation_host"])
        self.assertEqual(entry["virtualbox"], saved["virtualbox"])
        self.assertEqual(entry["docker"], saved["docker"])
        self.assertEqual(entry["ec2"], saved["ec2"])

    def test_resolve_workspace_accepts_legacy_selected_providers_key(self) -> None:
        entry = {
            "id": "ws_test",
            "name": "product · main",
            "connection": {"type": "local", "path": "/tmp/product"},
            "branch": "main",
            "selected_providers": {"target": "adb_usb"},
        }

        with (
            mock.patch("scripts.gar_lib.commands.workspace_resolver.load_config", return_value={}),
            mock.patch("scripts.gar_lib.commands.workspace_resolver.saved_workspaces", return_value=[entry]),
        ):
            workspace = resolve_workspace(None)

        self.assertEqual("adb_usb", workspace.selected_environments["target"])

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

            with mock.patch("scripts.gar_lib.core.config.CONFIG_PATH", config_path):
                config = load_config(workspace_selector="local/GarStreamRx")

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
                        "selected_environments": {"codespace": "wsl"},
                        "selected_target": "esp32",
                        "workspace": {"roots": ["/legacy"]},
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch("scripts.gar_lib.core.config.CONFIG_PATH", config_path):
                config = load_config()

        self.assertEqual([], config["workspaces"])
        self.assertEqual({}, config["selected_environments"])
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

    def test_target_manifest_resolves_target_owned_provisioning_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "gar-tools"
            target_dir = root / "targets" / "raspberry-pi-5"
            recipe = target_dir / "provisioning" / "raspberry-pi-os-systemd"
            recipe.mkdir(parents=True)
            (target_dir / "target.json").write_text(
                json.dumps(
                    {
                        "id": "raspberry-pi-5",
                        "displayName": "Raspberry Pi 5",
                        "description": "test target",
                        "toolsRoot": "targets/raspberry-pi-5",
                        "defaultBackends": {"target": "ssh_scp"},
                        "provisioning": {
                            "ssh_scp": {
                                "type": "ssh-script",
                                "path": "provisioning/raspberry-pi-os-systemd",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {"GAR_TOOLS_ROOT": str(root)}):
                target = discover_target_manifests()[0]
                resolved = target.provisioning_recipe_path("ssh_scp")

        self.assertEqual(recipe.resolve(), resolved)

    def test_ensure_gar_tools_available_clones_into_gar_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "GaplessAgentRuntime"
            project_root.mkdir()
            completed = subprocess.CompletedProcess(["git"], 0)
            with (
                mock.patch("scripts.gar_lib.core.tools_repository.PROJECT_ROOT", project_root),
                mock.patch.dict(os.environ, {"GAR_TOOLS_REPO": "https://example.invalid/gar-tools"}, clear=True),
                mock.patch("scripts.gar_lib.core.tools_repository.subprocess.run", return_value=completed) as run,
            ):
                root = ensure_gar_tools_available()

        self.assertEqual(project_root / ".gar" / "tools", root)
        run.assert_called_once_with(
            ["git", "clone", "--depth", "1", "https://example.invalid/gar-tools", str(project_root / ".gar" / "tools")],
            check=False,
        )

    def test_load_config_warns_on_invalid_json(self) -> None:
        from scripts.gar_lib.core.config import default_config

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / ".gar" / "config.json"
            config_path.parent.mkdir()
            config_path.write_text("{ not json", encoding="utf-8")

            stderr = io.StringIO()
            with (
                mock.patch("scripts.gar_lib.core.config.CONFIG_PATH", config_path),
                contextlib.redirect_stderr(stderr),
            ):
                config = load_config()

        self.assertEqual(default_config(), config)
        self.assertIn("not valid JSON", stderr.getvalue())

    def test_default_config_leaves_target_unselected(self) -> None:
        from scripts.gar_lib.core.config import default_config

        config = default_config()

        self.assertNotIn("selected_target", config)
        self.assertEqual({}, config["selected_environments"])
        self.assertNotIn("instance_id", config["ec2"])
        self.assertNotIn("region", config["ec2"])

    def test_save_config_is_atomic_and_leaves_no_temp_file(self) -> None:
        from scripts.gar_lib.core.config import save_config

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / ".gar" / "config.json"
            workspace_path = str(Path(tmp) / "product")

            with mock.patch("scripts.gar_lib.core.config.CONFIG_PATH", config_path):
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
                        "selected_environments": {"target": "ssh_scp"},
                    }
                )

            self.assertTrue(config_path.is_file())
            data = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual({"target": "ssh_scp"}, data["workspaces"][0]["selected_environments"])

            leftovers = [path for path in config_path.parent.iterdir() if path.name != config_path.name]
            self.assertEqual([], leftovers)

    def test_project_root_points_to_repository_root(self) -> None:
        """PROJECT_ROOT must resolve to the repo root, not scripts/."""
        from scripts.gar_lib.core.config import PROJECT_ROOT

        self.assertTrue(
            (PROJECT_ROOT / "AGENT.md").is_file(),
            f"PROJECT_ROOT={PROJECT_ROOT} is not the repository root " "(AGENT.md not found at expected location).",
        )
        self.assertTrue((PROJECT_ROOT / "scripts" / "gar_lib").is_dir())


if __name__ == "__main__":
    unittest.main()
