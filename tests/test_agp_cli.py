from __future__ import annotations

import contextlib
import io
import json
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from scripts.agp_lib.cli import (
    load_config,
    main,
    run_deploy_command,
    run_setup,
    run_sim_command,
    select_codespace_from_list,
    start_code_codespace,
    stop_code_codespace,
    run_terminal_request,
)
from scripts.agp_lib.environments.base import DevEnvironment


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
    def test_setup_lists_only_selected_provider_for_configured_category(self) -> None:
        providers = [DevelopmentProvider, SimulationProvider, DeviceProvider]
        config = {
            "selected_providers": {
                "development": "development_test",
                "simulation": "simulation_test",
                "device": "device_test",
            }
        }

        with (
            mock.patch("scripts.agp_lib.cli.discover_environment_providers", return_value=providers),
            mock.patch("scripts.agp_lib.cli.load_config", return_value=config),
            mock.patch("scripts.agp_lib.cli.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("builtins.input", return_value=""),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_setup(no_install=True)

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

    def test_setup_defaults_to_first_unconfigured_category_provider(self) -> None:
        providers = [DevelopmentProvider, MissingProvider]
        config = {"selected_providers": {"development": "development_test"}}

        with (
            mock.patch("scripts.agp_lib.cli.discover_environment_providers", return_value=providers),
            mock.patch("scripts.agp_lib.cli.load_config", return_value=config),
            mock.patch("scripts.agp_lib.cli.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("builtins.input", side_effect=["", "", "q"]),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_setup(no_install=True)

        self.assertEqual(1, result)
        text = output.getvalue()
        self.assertIn("未設定", text)
        self.assertIn("選択: Missing Test", text)
        self.assertIn("2. 実機環境", text)
        self.assertIn("未完了のセットアップ", text)

    def test_setup_saves_selected_provider_after_successful_setup(self) -> None:
        providers = [DevelopmentProvider]
        config = {"selected_providers": {}}

        with (
            mock.patch("scripts.agp_lib.cli.discover_environment_providers", return_value=providers),
            mock.patch("scripts.agp_lib.cli.load_config", return_value=config),
            mock.patch("scripts.agp_lib.cli.save_config") as save_config,
            mock.patch("scripts.agp_lib.cli.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("builtins.input", side_effect=["", "", ""]),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_setup(no_install=True)

        self.assertEqual(0, result)
        save_config.assert_called_once_with(
            {"selected_providers": {"development": "development_test"}}
        )

    def test_terminal_run_creates_vscode_terminal_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with (
                mock.patch("scripts.agp_lib.cli.CONFIG_PATH", tmp_path / ".agp" / "config.json"),
                mock.patch("scripts.agp_lib.cli.Path.cwd", return_value=tmp_path),
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

    def test_sim_status_uses_configured_ec2_host_when_host_is_omitted(self) -> None:
        config = {
            "selected_providers": {},
            "ec2": {"host": "configured-ec2"},
        }

        with (
            mock.patch("scripts.agp_lib.cli.load_config", return_value=config),
            mock.patch("scripts.agp_lib.cli.status_sim_port_forward", return_value=0) as status,
            mock.patch("scripts.agp_lib.cli.show_sim_state", return_value=0) as state,
        ):
            result = run_sim_command("status")

        self.assertEqual(0, result)
        status.assert_called_once_with("configured-ec2")
        state.assert_called_once_with("configured-ec2")

    def test_sim_start_only_starts_device_runtime(self) -> None:
        with (
            mock.patch("scripts.agp_lib.cli.subprocess.run") as run,
            mock.patch("scripts.agp_lib.cli.write_sim_terminal_profile"),
        ):
            run.return_value.returncode = 0

            result = run_sim_command("start", host="ec2-test", port_forward=False)

        self.assertEqual(0, result)
        remote_command = run.call_args.args[0][-1]
        self.assertIn("bridge.py", remote_command)
        self.assertIn("cuse_i2c", remote_command)
        self.assertNotIn("sensor_demo", remote_command)
        self.assertNotIn("LD_PRELOAD", remote_command)

    def test_sim_start_writes_terminal_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings = home / "settings.json"

            with (
                mock.patch("scripts.agp_lib.cli.Path.home", return_value=home),
                mock.patch("scripts.agp_lib.cli.subprocess.run") as run,
            ):
                run.return_value.returncode = 0
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = run_sim_command(
                        "start",
                        host="ec2-test",
                        settings=str(settings),
                        port_forward=False,
                    )

            self.assertEqual(0, result)
            terminal = home / ".local" / "bin" / "agp-sim-terminal"
            self.assertIn("ssh -F", terminal.read_text(encoding="utf-8"))
            self.assertIn("ec2-test", terminal.read_text(encoding="utf-8"))
            profile = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(
                {"path": str(terminal)},
                profile["terminal.integrated.profiles.linux"]["EC2 Simulation"],
            )

    def test_sim_start_starts_port_forward(self) -> None:
        with (
            mock.patch("scripts.agp_lib.cli.subprocess.run") as run,
            mock.patch("scripts.agp_lib.cli.write_sim_terminal_profile"),
            mock.patch("scripts.agp_lib.cli.start_sim_port_forward", return_value=0) as forward,
        ):
            run.return_value.returncode = 0

            result = run_sim_command("start", host="ec2-test")

        self.assertEqual(0, result)
        forward.assert_called_once_with("ec2-test")

    def test_sim_status_checks_port_forward(self) -> None:
        with (
            mock.patch("scripts.agp_lib.cli.status_sim_port_forward", return_value=0) as status,
            mock.patch("scripts.agp_lib.cli.show_sim_state", return_value=0) as state,
        ):
            result = run_sim_command("status", host="ec2-test")

        self.assertEqual(0, result)
        status.assert_called_once_with("ec2-test")
        state.assert_called_once_with("ec2-test")

    def test_deploy_sim_copies_artifacts_to_configured_ec2_host(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "files" / "bin").mkdir(parents=True)
            (root / "files" / "bin" / "sensor_demo").write_text("", encoding="utf-8")
            (root / "files" / "web-bridge").mkdir(parents=True)
            (root / "files" / "web-bridge" / "bridge.py").write_text("", encoding="utf-8")
            (root / "artifact.json").write_text(
                json.dumps(
                    {
                        "name": "sensor-demo",
                        "deploy": {
                            "sim": {
                                "files": [
                                    {
                                        "src": "files/bin/sensor_demo",
                                        "dest": "~/sensor_demo",
                                        "mode": "0755",
                                    },
                                    {
                                        "src": "files/web-bridge",
                                        "dest": "~/web-bridge",
                                    },
                                ]
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            config = {"selected_providers": {}, "ec2": {"host": "configured-ec2"}}
            with (
                mock.patch("scripts.agp_lib.cli.load_config", return_value=config),
                mock.patch("scripts.agp_lib.cli.subprocess.run") as run,
            ):
                run.return_value.returncode = 0

                result = run_deploy_command("sim", artifacts_dir=str(root))

        self.assertEqual(0, result)
        self.assertEqual(3, run.call_count)
        file_copy = run.call_args_list[0].args[0]
        chmod = run.call_args_list[1].args[0]
        dir_copy = run.call_args_list[2].args[0]
        self.assertEqual("scp", file_copy[0])
        self.assertEqual("configured-ec2:~/sensor_demo", file_copy[-1])
        self.assertEqual(["ssh", "-F"], chmod[:2])
        self.assertEqual(["configured-ec2", "chmod", "0755", "~/sensor_demo"], chmod[-4:])
        self.assertIn("-r", dir_copy)
        self.assertEqual("configured-ec2:~/web-bridge", dir_copy[-1])

    def test_deploy_native_pushes_sensor_demo_with_adb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "files" / "sensor_demo"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("", encoding="utf-8")
            (root / "artifact.json").write_text(
                json.dumps(
                    {
                        "name": "sensor-demo",
                        "deploy": {
                            "native": {
                                "files": [
                                    {
                                        "src": "files/sensor_demo",
                                        "dest": "/home/user/sensor_demo",
                                        "mode": "0755",
                                    }
                                ]
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch("scripts.agp_lib.cli.subprocess.run") as run:
                run.return_value.returncode = 0

                result = run_deploy_command(
                    "native",
                    artifacts_dir=str(root),
                    serial="raspi",
                    dest="/home/user",
                )

        self.assertEqual(0, result)
        self.assertEqual(2, run.call_count)
        push_argv = run.call_args_list[0].args[0]
        chmod_argv = run.call_args_list[1].args[0]
        self.assertEqual(["adb", "-s", "raspi", "push"], push_argv[:4])
        self.assertEqual("/home/user/sensor_demo", push_argv[-1])
        self.assertEqual(["adb", "-s", "raspi", "shell", "chmod", "0755", "/home/user/sensor_demo"], chmod_argv)

    def test_sim_deploy_is_available_from_cli(self) -> None:
        with mock.patch("scripts.agp_lib.cli.run_deploy_command", return_value=0) as run_deploy:
            result = main(["sim", "deploy", "--host", "ec2-test"])

        self.assertEqual(0, result)
        run_deploy.assert_called_once_with(
            "sim",
            artifacts_dir=None,
            host="ec2-test",
        )

    def test_native_deploy_is_available_from_cli(self) -> None:
        with mock.patch("scripts.agp_lib.cli.run_deploy_command", return_value=0) as run_deploy:
            result = main(["native", "deploy", "--serial", "raspi"])

        self.assertEqual(0, result)
        run_deploy.assert_called_once_with(
            "native",
            artifacts_dir=None,
            serial="raspi",
            dest="/home/user",
        )

    def test_code_start_is_available_from_cli(self) -> None:
        with mock.patch("scripts.agp_lib.cli.run_code_command", return_value=0) as run_code:
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
        )

    def test_code_start_writes_codespace_state_and_terminal_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings = home / "settings.json"

            def run_side_effect(argv, **kwargs):
                completed = mock.Mock()
                completed.returncode = 0
                completed.stdout = ""
                if argv[:4] == ["gh", "codespace", "ssh", "-c"]:
                    completed.stdout = "Host codespace-host\n  HostName example\n"
                return completed

            with (
                mock.patch("scripts.agp_lib.cli.Path.home", return_value=home),
                mock.patch("scripts.agp_lib.cli.shutil.which", return_value="/usr/bin/tool"),
                mock.patch("scripts.agp_lib.cli.subprocess.run", side_effect=run_side_effect),
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
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
            terminal = home / ".local" / "bin" / "codespace-terminal"
            self.assertIn("Run: agp code start", terminal.read_text(encoding="utf-8"))
            profile = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(
                {"path": str(terminal)},
                profile["terminal.integrated.profiles.linux"]["Codespaces"],
            )

    def test_code_start_can_select_single_listed_codespace(self) -> None:
        output = "single-codespace\towner/repo\tmain\tStopped\tShutdown\t1h\n"

        self.assertEqual("single-codespace", select_codespace_from_list(output))

    def test_code_start_selects_first_available_when_multiple_codespaces_exist(self) -> None:
        output = "\n".join(
            [
                "stopped-codespace\towner/repo\tmain\tStopped\tShutdown\t1h",
                "available-codespace\towner/repo\tmain\tRunning\tAvailable\t2h",
                "other-codespace\towner/repo\tmain\tRunning\tAvailable\t3h",
            ]
        )

        self.assertEqual("available-codespace", select_codespace_from_list(output))

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
                mock.patch("scripts.agp_lib.cli.Path.home", return_value=home),
                mock.patch("scripts.agp_lib.cli.shutil.which", return_value="/usr/bin/tool"),
                mock.patch("scripts.agp_lib.cli.subprocess.run", side_effect=run_side_effect) as run,
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

    def test_code_stop_is_available_from_cli(self) -> None:
        with mock.patch("scripts.agp_lib.cli.run_code_command", return_value=0) as run_code:
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
        )

    def test_code_stop_unmounts_codespace_and_removes_terminal_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            mount_dir = home / "codespaces" / "AgentCockpit"
            mount_dir.mkdir(parents=True)
            state_dir = home / ".config" / "codespace-dev"
            state_dir.mkdir(parents=True)
            (state_dir / "env").write_text(
                "\n".join(
                    [
                        "CODESPACE_SSH_HOST='codespace-host'",
                        "CODESPACE_REMOTE_PATH='/workspaces/AgentCockpit'",
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
                    completed.stdout = "codespace-host:/workspaces/AgentCockpit\n"
                return completed

            with (
                mock.patch("scripts.agp_lib.cli.Path.home", return_value=home),
                mock.patch("scripts.agp_lib.cli.shutil.which", return_value="/usr/bin/tool"),
                mock.patch("scripts.agp_lib.cli.subprocess.run", side_effect=run_side_effect) as run,
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

    def test_sim_start_is_available_from_cli(self) -> None:
        with mock.patch("scripts.agp_lib.cli.run_sim_command", return_value=0) as run_sim:
            result = main(
                [
                    "sim",
                    "start",
                    "--host",
                    "ec2-test",
                    "--settings",
                    "settings.json",
                    "--profile-name",
                    "Simulation",
                ]
            )

        self.assertEqual(0, result)
        run_sim.assert_called_once_with(
            "start",
            host="ec2-test",
            settings="settings.json",
            profile_name="Simulation",
            port_forward=True,
            stop_port_forward=True,
        )

    def test_sim_cli_omits_host_by_default(self) -> None:
        with mock.patch("scripts.agp_lib.cli.run_sim_command", return_value=0) as run_sim:
            result = main(["sim", "start"])

        self.assertEqual(0, result)
        run_sim.assert_called_once_with(
            "start",
            host=None,
            settings=None,
            profile_name=None,
            port_forward=True,
            stop_port_forward=True,
        )

    def test_sim_status_is_available_from_cli(self) -> None:
        with mock.patch("scripts.agp_lib.cli.run_sim_command", return_value=0) as run_sim:
            result = main(["sim", "status", "--host", "ec2-test"])

        self.assertEqual(0, result)
        run_sim.assert_called_once_with(
            "status",
            host="ec2-test",
            settings=None,
            profile_name=None,
            port_forward=True,
            stop_port_forward=True,
        )

    def test_setup_can_store_default_ec2_host(self) -> None:
        providers = [DevelopmentProvider]
        config = {"selected_providers": {}}

        with (
            mock.patch("scripts.agp_lib.cli.discover_environment_providers", return_value=providers),
            mock.patch("scripts.agp_lib.cli.load_config", return_value=config),
            mock.patch("scripts.agp_lib.cli.save_config") as save_config,
            mock.patch("scripts.agp_lib.cli.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("builtins.input", side_effect=["", "", ""]),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_setup(no_install=True, ec2_host="configured-ec2")

        self.assertEqual(0, result)
        save_config.assert_any_call(
            {
                "selected_providers": {"development": "development_test"},
                "ec2": {"host": "configured-ec2"},
            }
        )

    def test_load_config_keeps_legacy_config_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / ".agp" / "config.json"
            config_path.parent.mkdir()
            config_path.write_text(
                json.dumps({"selected_providers": {"development": "wsl"}}),
                encoding="utf-8",
            )

            with mock.patch("scripts.agp_lib.cli.CONFIG_PATH", config_path):
                config = load_config()

        self.assertEqual("wsl", config["selected_providers"]["development"])
        self.assertEqual("vibecode-graviton", config["ec2"]["host"])


if __name__ == "__main__":
    unittest.main()
