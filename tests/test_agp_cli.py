from __future__ import annotations

import contextlib
import io
import json
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from agp.cli import run_init, run_terminal_request
from agp.environments.base import DevEnvironment


class DevelopmentProvider(DevEnvironment):
    provider_id = "development_test"
    display_name = "Development Test"
    description = "development"
    category_id = "development"
    category_name = "開発環境"
    required_commands = ()


class SimulationProvider(DevEnvironment):
    provider_id = "simulation_test"
    display_name = "Simulation Test"
    description = "simulation"
    category_id = "simulation"
    category_name = "シミュレート環境"
    required_commands = ()


class DeviceProvider(DevEnvironment):
    provider_id = "device_test"
    display_name = "Device Test"
    description = "device"
    category_id = "device"
    category_name = "実機環境"
    required_commands = ()


class MissingProvider(DevEnvironment):
    provider_id = "missing_test"
    display_name = "Missing Test"
    description = "missing"
    category_id = "device"
    category_name = "実機環境"
    required_commands = ("missing-command",)


class AgpCliTest(unittest.TestCase):
    def test_init_lists_only_selected_provider_for_configured_category(self) -> None:
        providers = [DevelopmentProvider, SimulationProvider, DeviceProvider]
        config = {
            "selected_providers": {
                "development": "development_test",
                "simulation": "simulation_test",
                "device": "device_test",
            }
        }

        with (
            mock.patch("agp.cli.discover_environment_providers", return_value=providers),
            mock.patch("agp.cli.load_config", return_value=config),
            mock.patch("agp.cli.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("builtins.input", return_value=""),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_init(no_install=True)

        self.assertEqual(0, result)
        text = output.getvalue()
        self.assertIn("1. 開発環境", text)
        self.assertIn("2. シミュレート環境", text)
        self.assertIn("3. 実機環境", text)
        self.assertIn("VSCode Terminal Bridge:", text)
        self.assertIn("未導入", text)
        self.assertIn("設定済み", text)
        self.assertNotIn("1. Development Test", text)
        self.assertIn("初期化が完了しました。", text)

    def test_init_defaults_to_first_unconfigured_category_provider(self) -> None:
        providers = [DevelopmentProvider, MissingProvider]
        config = {"selected_providers": {"development": "development_test"}}

        with (
            mock.patch("agp.cli.discover_environment_providers", return_value=providers),
            mock.patch("agp.cli.load_config", return_value=config),
            mock.patch("agp.cli.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("builtins.input", side_effect=["", "", "q"]),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_init(no_install=True)

        self.assertEqual(1, result)
        text = output.getvalue()
        self.assertIn("未設定", text)
        self.assertIn("選択: Missing Test", text)
        self.assertIn("2. 実機環境", text)
        self.assertIn("未完了のセットアップ", text)

    def test_init_saves_selected_provider_after_successful_setup(self) -> None:
        providers = [DevelopmentProvider]
        config = {"selected_providers": {}}

        with (
            mock.patch("agp.cli.discover_environment_providers", return_value=providers),
            mock.patch("agp.cli.load_config", return_value=config),
            mock.patch("agp.cli.save_config") as save_config,
            mock.patch("agp.cli.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("builtins.input", side_effect=["", "", ""]),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_init(no_install=True)

        self.assertEqual(0, result)
        save_config.assert_called_once_with(
            {"selected_providers": {"development": "development_test"}}
        )

    def test_terminal_run_creates_vscode_terminal_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with (
                mock.patch("agp.cli.CONFIG_PATH", tmp_path / ".agp" / "config.json"),
                mock.patch("agp.cli.Path.cwd", return_value=tmp_path),
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
            requests = list((tmp_path / ".agp" / "terminal-requests").glob("*.json"))
            self.assertEqual(1, len(requests))

            request = json.loads(requests[0].read_text(encoding="utf-8"))
            self.assertEqual("Test Terminal", request["title"])
            self.assertEqual("echo hello", request["command"])
            self.assertEqual(str(tmp_path), request["cwd"])


if __name__ == "__main__":
    unittest.main()
