from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from scripts.agp_lib._sim_parse import parse_gpio_runtime_status, parse_gpio_sim_check, parse_sim_diag
from scripts.agp_lib.sim.linux import LinuxSimCommandBuilder, gpio_sim_plan
from scripts.agp_lib.cli import (
    adb_device_available,
    completion_bash_script,
    ensure_adb_device,
    fetch_codespace_artifacts,
    load_config,
    main,
    normalize_question_help,
    parse_usbipd_list,
    run_deploy_command,
    run_ec2_command,
    run_gpio_sim_check,
    run_native_sync_command,
    run_setup,
    run_sim_command,
    run_sim_gpio_command,
    run_sim_panel,
    run_terminal_request,
    run_usb_command,
    select_codespace_from_list,
    start_code_codespace,
    stop_code_codespace,
    update_ssh_config_hostname,
)
from scripts.agp_lib.environments.base import DevEnvironment
from scripts.agp_lib.environments.registry.simulation.ssh_remote import SshRemoteEnvironment


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
    def test_question_mark_prints_contextual_help(self) -> None:
        cases = [
            (["?"], "usage: agp", "code"),
            (["code", "?"], "usage: agp code", "start"),
            (["sim", "gpio", "?"], "usage: agp sim gpio", "plan"),
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
        self.assertIn("register-python-argcomplete agp", text)
        self.assertIn("eval", text)
        self.assertIn("completion words", text)

    def test_completion_bash_is_available_from_cli(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["completion", "bash"])

        self.assertEqual(0, result)
        self.assertIn("register-python-argcomplete agp", output.getvalue())

    def test_completion_words_uses_parser_commands(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["completion", "words", "--cword", "2", "--", "agp", "sim", ""])

        self.assertEqual(0, result)
        self.assertIn("env", output.getvalue().splitlines())
        self.assertIn("ui", output.getvalue().splitlines())

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
            mock.patch("scripts.agp_lib._setup.discover_environment_providers", return_value=providers),
            mock.patch("scripts.agp_lib._setup.load_config", return_value=config),
            mock.patch("scripts.agp_lib._setup.installed_vscode_terminal_bridge_path", return_value=None),
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
            mock.patch("scripts.agp_lib._setup.discover_environment_providers", return_value=providers),
            mock.patch("scripts.agp_lib._setup.load_config", return_value=config),
            mock.patch("scripts.agp_lib._setup.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("builtins.input", side_effect=["", "", "", "q"]),
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
            mock.patch("scripts.agp_lib._setup.discover_environment_providers", return_value=providers),
            mock.patch("scripts.agp_lib._setup.load_config", return_value=config),
            mock.patch("scripts.agp_lib._setup.save_config") as save_config,
            mock.patch("scripts.agp_lib._setup.installed_vscode_terminal_bridge_path", return_value=None),
            mock.patch("builtins.input", side_effect=["", "", "", "q"]),
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
                mock.patch("scripts.agp_lib._terminal.CONFIG_PATH", tmp_path / ".agp" / "config.json"),
                mock.patch("scripts.agp_lib._terminal.Path.cwd", return_value=tmp_path),
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
            mock.patch("scripts.agp_lib._sim.load_config", return_value=config),
            mock.patch("scripts.agp_lib._sim.status_sim_port_forward", return_value=0) as status,
            mock.patch("scripts.agp_lib._sim.show_sim_state", return_value=0) as state,
        ):
            result = run_sim_command("status")

        self.assertEqual(0, result)
        status.assert_called_once_with("configured-ec2")
        state.assert_called_once_with("configured-ec2")

    def test_ec2_status_uses_configured_instance_and_region(self) -> None:
        config = {
            "selected_providers": {},
            "ec2": {
                "host": "configured-ec2",
                "instance_id": "i-test123",
                "region": "ap-test-1",
            },
        }
        with (
            mock.patch("scripts.agp_lib._ec2._aws_available", return_value=True),
            mock.patch("scripts.agp_lib._ec2.load_config", return_value=config),
            mock.patch(
                "scripts.agp_lib._ec2.ec2_instance_state", return_value="running"
            ) as state,
            mock.patch(
                "scripts.agp_lib._ec2.ec2_public_ip", return_value="203.0.113.5"
            ) as ip,
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_ec2_command("status")

        self.assertEqual(0, result)
        state.assert_called_once_with("i-test123", "ap-test-1")
        ip.assert_called_once_with("i-test123", "ap-test-1")
        self.assertIn("203.0.113.5", output.getvalue())

    def test_ec2_start_updates_ssh_config_hostname(self) -> None:
        config = {
            "selected_providers": {},
            "ec2": {
                "host": "configured-ec2",
                "instance_id": "i-test123",
                "region": "ap-test-1",
            },
        }
        completed = mock.Mock(returncode=0, stdout="", stderr="")
        with (
            mock.patch("scripts.agp_lib._ec2._aws_available", return_value=True),
            mock.patch("scripts.agp_lib._ec2.load_config", return_value=config),
            mock.patch(
                "scripts.agp_lib._ec2._run_aws", return_value=completed
            ) as run_aws,
            mock.patch(
                "scripts.agp_lib._ec2.ec2_public_ip", return_value="203.0.113.5"
            ),
            mock.patch(
                "scripts.agp_lib._ec2.update_ssh_config_hostname", return_value=True
            ) as update_ssh,
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_ec2_command("start")

        self.assertEqual(0, result)
        update_ssh.assert_called_once_with("configured-ec2", "203.0.113.5")
        first_aws_args = run_aws.call_args_list[0].args[0]
        self.assertIn("start-instances", first_aws_args)
        self.assertIn("i-test123", first_aws_args)

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

            updated = update_ssh_config_hostname(
                "vibecode-graviton", "203.0.113.5", path=config_path
            )

            self.assertTrue(updated)
            contents = config_path.read_text(encoding="utf-8")
            self.assertIn("HostName 203.0.113.5", contents)
            self.assertIn("HostName 198.51.100.1", contents)

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
            mock.patch("scripts.agp_lib._usb._usbipd_executable", return_value="usbipd.exe"),
            mock.patch(
                "scripts.agp_lib._usb.list_usb_devices",
                return_value=parse_usbipd_list(output),
            ),
            mock.patch("scripts.agp_lib._usb.load_config", return_value={"selected_providers": {}}),
            mock.patch("scripts.agp_lib._usb.save_config", side_effect=lambda c: saved.update(c)),
            mock.patch("scripts.agp_lib._usb._run_usbipd") as run_usbipd,
        ):
            run_usbipd.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            output_buffer = io.StringIO()
            with contextlib.redirect_stdout(output_buffer):
                result = run_usb_command("attach")

        self.assertEqual(0, result)
        run_usbipd.assert_called_once_with(["attach", "--wsl", "--busid", "2-3"])
        self.assertEqual("2-3", saved.get("usb", {}).get("busid"))

    def test_usb_attach_hints_bind_when_not_shared(self) -> None:
        output = (
            "Connected:\n"
            "BUSID  VID:PID    DEVICE             STATE\n"
            "2-3    18d1:4ee7  Android ADB        Not shared\n"
        )
        with (
            mock.patch("scripts.agp_lib._usb._usbipd_executable", return_value="usbipd.exe"),
            mock.patch(
                "scripts.agp_lib._usb.list_usb_devices",
                return_value=parse_usbipd_list(output),
            ),
            mock.patch("scripts.agp_lib._usb.load_config", return_value={"selected_providers": {}}),
            mock.patch("scripts.agp_lib._usb._run_usbipd") as run_usbipd,
        ):
            err_buffer = io.StringIO()
            with contextlib.redirect_stderr(err_buffer):
                result = run_usb_command("attach")

        self.assertEqual(1, result)
        run_usbipd.assert_not_called()
        self.assertIn("usbipd bind --busid 2-3", err_buffer.getvalue())

    def test_sim_start_only_starts_device_runtime(self) -> None:
        with (
            mock.patch("scripts.agp_lib.environments.registry.simulation.ssh_remote.SshRemoteEnvironment.run_remote") as run,
            mock.patch("scripts.agp_lib._sim.write_sim_terminal_profile"),
            mock.patch("scripts.agp_lib._sim._get_sim_provider", return_value=SshRemoteEnvironment),
        ):
            run.return_value.returncode = 0

            result = run_sim_command("start", host="ec2-test", port_forward=False)

        self.assertEqual(0, result)
        remote_command = run.call_args.args[1]
        self.assertIn("bridge.py", remote_command)
        self.assertIn("cuse_i2c", remote_command)
        self.assertIn("agp-sim.target", remote_command)
        self.assertIn("systemctl start", remote_command)
        self.assertIn("/etc/agentcockpit/hardware", remote_command)
        self.assertIn("/usr/local/sbin/cuse_i2c", remote_command)
        self.assertIn("/usr/local/sbin/cuse_spi", remote_command)
        self.assertIn("/usr/local/lib/agentcockpit/web-bridge/bridge.py", remote_command)
        self.assertIn("/run/agentcockpit", remote_command)
        self.assertIn("AGP_HW_SIM_SOCK=/run/agentcockpit/hw_sim.sock", remote_command)
        self.assertNotIn("sensor_demo", remote_command)
        self.assertNotIn("LD_PRELOAD", remote_command)

    def test_sim_start_prepares_gpio_sim_as_gpiochip0(self) -> None:
        with (
            mock.patch("scripts.agp_lib.environments.registry.simulation.ssh_remote.SshRemoteEnvironment.run_remote") as run,
            mock.patch("scripts.agp_lib._sim.write_sim_terminal_profile"),
            mock.patch("scripts.agp_lib._sim._get_sim_provider", return_value=SshRemoteEnvironment),
        ):
            run.return_value.returncode = 0

            result = run_sim_command("start", host="ec2-test", port_forward=False)

        self.assertEqual(0, result)
        remote_command = run.call_args.args[1]
        self.assertIn("modprobe gpio-sim", remote_command)
        self.assertIn("mount --bind", remote_command)
        self.assertIn("/dev/gpiochip0", remote_command)
        self.assertIn("BTN_GPIO17", remote_command)
        self.assertIn("LED_GPIO18", remote_command)

    def test_sim_start_uses_hardware_csv_for_runtime_devices(self) -> None:
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
            "i2c": [{"dev": "/dev/i2c-2"}],
            "spi": [{"dev": "/dev/spidev1.0"}],
        }
        with (
            mock.patch("scripts.agp_lib._sim.load_hw_definition", return_value=hw_definition),
            mock.patch("scripts.agp_lib.environments.registry.simulation.ssh_remote.SshRemoteEnvironment.run_remote") as run,
            mock.patch("scripts.agp_lib._sim.write_sim_terminal_profile"),
            mock.patch("scripts.agp_lib._sim._get_sim_provider", return_value=SshRemoteEnvironment),
        ):
            run.return_value.returncode = 0

            result = run_sim_command("start", host="ec2-test", port_forward=False)

        self.assertEqual(0, result)
        remote_command = run.call_args.args[1]
        self.assertIn("/dev/gpiochip2", remote_command)
        self.assertIn("BTN_GPIO5", remote_command)
        self.assertIn("LED_GPIO6", remote_command)
        self.assertIn("--devname=%i", remote_command)
        self.assertIn("agp-cuse-i2c@i2c-2.service", remote_command)
        self.assertIn("agp-cuse-spi@spidev1.0.service", remote_command)

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

    def test_sim_gpio_start_installs_and_restarts_gpio_service(self) -> None:
        with (
            mock.patch("scripts.agp_lib.environments.registry.simulation.ssh_remote.SshRemoteEnvironment.run_remote") as run,
            mock.patch("scripts.agp_lib._sim._get_sim_provider", return_value=SshRemoteEnvironment),
        ):
            run.return_value.returncode = 0

            result = run_sim_gpio_command("start", host="ec2-test")

        self.assertEqual(0, result)
        remote_command = run.call_args.args[1]
        self.assertIn("modprobe gpio-sim", remote_command)
        self.assertIn("/usr/local/sbin/agp-gpio-sim-start", remote_command)
        self.assertIn("/etc/systemd/system/agp-gpio-sim.service", remote_command)
        self.assertIn("systemctl restart agp-gpio-sim.service", remote_command)
        self.assertNotIn("agp-bridge.service", remote_command)
        self.assertNotIn("cuse_i2c", remote_command)

    def test_sim_stop_tears_down_gpio_sim(self) -> None:
        with mock.patch("scripts.agp_lib.environments.registry.simulation.ssh_remote.SshRemoteEnvironment.run_remote") as run:
            with mock.patch("scripts.agp_lib._sim._get_sim_provider", return_value=SshRemoteEnvironment):
                run.return_value.returncode = 0

                result = run_sim_command("stop", host="ec2-test", stop_port_forward=False)

        self.assertEqual(0, result)
        remote_command = run.call_args.args[1]
        self.assertIn("systemctl stop agp-sim.target", remote_command)
        self.assertIn("agp-gpio-sim.service", remote_command)
        self.assertIn("sudo pkill -x cuse_i2c", remote_command)
        self.assertIn("pkill -f '[/]web-bridge/bridge.py'", remote_command)

    def test_sim_start_writes_terminal_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings = home / "settings.json"

            with (
                mock.patch("scripts.agp_lib._sim.Path.home", return_value=home),
                mock.patch("scripts.agp_lib.environments.registry.simulation.ssh_remote.SshRemoteEnvironment.run_remote") as run,
                mock.patch("scripts.agp_lib._sim._get_sim_provider", return_value=SshRemoteEnvironment),
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
            mock.patch("scripts.agp_lib.environments.registry.simulation.ssh_remote.SshRemoteEnvironment.run_remote") as run,
            mock.patch("scripts.agp_lib._sim.write_sim_terminal_profile"),
            mock.patch("scripts.agp_lib._sim.start_sim_port_forward", return_value=0) as forward,
            mock.patch("scripts.agp_lib._sim._get_sim_provider", return_value=SshRemoteEnvironment),
        ):
            run.return_value.returncode = 0

            result = run_sim_command("start", host="ec2-test")

        self.assertEqual(0, result)
        forward.assert_called_once_with("ec2-test")

    def test_sim_status_checks_port_forward(self) -> None:
        with (
            mock.patch("scripts.agp_lib._sim.status_sim_port_forward", return_value=0) as status,
            mock.patch("scripts.agp_lib._sim.show_sim_state", return_value=0) as state,
        ):
            result = run_sim_command("status", host="ec2-test")

        self.assertEqual(0, result)
        status.assert_called_once_with("ec2-test")
        state.assert_called_once_with("ec2-test")

    def test_sim_status_json_returns_bridge_state(self) -> None:
        with mock.patch("scripts.agp_lib.sim.linux.LinuxSystemdSimProvider.panel", return_value=0) as panel:
            result = run_sim_command("status", host="ec2-test", json_output=True)

        self.assertEqual(0, result)
        panel.assert_called_once_with("state", params={}, json_output=True)

    def test_deploy_sim_copies_artifacts_to_configured_ec2_host(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "files" / "bin").mkdir(parents=True)
            (root / "files" / "bin" / "sensor_demo").write_text("", encoding="utf-8")
            (root / "files" / "cuse_i2c").write_text("", encoding="utf-8")
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
                                        "src": "files/cuse_i2c",
                                        "dest": "~/cuse_i2c",
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
                mock.patch("scripts.agp_lib._deploy.load_config", return_value=config),
                mock.patch("scripts.agp_lib._deploy.subprocess.run") as run,
            ):
                run.return_value.returncode = 0

                result = run_deploy_command("sim", artifacts_dir=str(root))

        self.assertEqual(0, result)
        self.assertEqual(6, run.call_count)
        file_copy = run.call_args_list[0].args[0]
        file_install = run.call_args_list[1].args[0]
        cuse_copy = run.call_args_list[2].args[0]
        cuse_install = run.call_args_list[3].args[0]
        dir_copy = run.call_args_list[4].args[0]
        dir_install = run.call_args_list[5].args[0]
        self.assertEqual("scp", file_copy[0])
        self.assertIn("configured-ec2:/tmp/agentcockpit-deploy-", file_copy[-1])
        self.assertEqual(["ssh", "-F"], file_install[:2])
        self.assertEqual("configured-ec2", file_install[3])
        self.assertIn('"${HOME}"/', file_install[-1])
        self.assertIn("chmod '0755'", file_install[-1])
        self.assertEqual("scp", cuse_copy[0])
        self.assertIn("configured-ec2:/tmp/agentcockpit-deploy-", cuse_copy[-1])
        self.assertEqual(["ssh", "-F"], cuse_install[:2])
        self.assertIn("/usr/local/sbin/cuse_i2c", cuse_install[-1])
        self.assertIn("sudo chmod '0755'", cuse_install[-1])
        self.assertIn("-r", dir_copy)
        self.assertIn("configured-ec2:/tmp/agentcockpit-deploy-", dir_copy[-1])
        self.assertEqual(["ssh", "-F"], dir_install[:2])
        self.assertEqual("configured-ec2", dir_install[3])
        self.assertIn("/usr/local/lib/agentcockpit/web-bridge", dir_install[-1])
        self.assertIn("sudo cp -a", dir_install[-1])

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

            def run_side_effect(argv, **kwargs):
                if argv == ["adb", "devices"]:
                    return subprocess.CompletedProcess(
                        args=argv,
                        returncode=0,
                        stdout="List of devices attached\nraspi\tdevice\n",
                        stderr="",
                    )
                return subprocess.CompletedProcess(args=argv, returncode=0)

            with mock.patch("scripts.agp_lib._deploy.subprocess.run", side_effect=run_side_effect) as run:

                result = run_deploy_command(
                    "native",
                    artifacts_dir=str(root),
                    serial="raspi",
                    dest="/home/user",
                )

        self.assertEqual(0, result)
        self.assertEqual(3, run.call_count)
        devices_argv = run.call_args_list[0].args[0]
        push_argv = run.call_args_list[1].args[0]
        chmod_argv = run.call_args_list[2].args[0]
        self.assertEqual(["adb", "devices"], devices_argv)
        self.assertEqual(["adb", "-s", "raspi", "push"], push_argv[:4])
        self.assertEqual("/home/user/sensor_demo", push_argv[-1])
        self.assertEqual(["adb", "-s", "raspi", "shell", "chmod 0755 /home/user/sensor_demo"], chmod_argv)

    def test_adb_device_available_checks_serial_when_given(self) -> None:
        output = "List of devices attached\nraspi\tdevice\nother\toffline\n"
        self.assertTrue(adb_device_available(output, serial=None))
        self.assertTrue(adb_device_available(output, serial="raspi"))
        self.assertFalse(adb_device_available(output, serial="missing"))
        self.assertFalse(adb_device_available("List of devices attached\n", serial=None))

    def test_native_deploy_auto_attaches_usb_when_adb_device_is_missing(self) -> None:
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

            devices_calls = 0

            def run_side_effect(argv, **kwargs):
                nonlocal devices_calls
                if argv == ["adb", "devices"]:
                    devices_calls += 1
                    stdout = (
                        "List of devices attached\n"
                        if devices_calls == 1
                        else "List of devices attached\nraspi\tdevice\n"
                    )
                    return subprocess.CompletedProcess(args=argv, returncode=0, stdout=stdout, stderr="")
                return subprocess.CompletedProcess(args=argv, returncode=0)

            with (
                mock.patch("scripts.agp_lib._deploy.subprocess.run", side_effect=run_side_effect) as run,
                mock.patch("scripts.agp_lib._deploy.run_usb_command", return_value=0) as usb_attach,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                result = run_deploy_command(
                    "native",
                    artifacts_dir=str(root),
                    serial="raspi",
                    dest="/home/user",
                )

        self.assertEqual(0, result)
        usb_attach.assert_called_once_with("attach")
        self.assertEqual(4, run.call_count)
        self.assertEqual(["adb", "devices"], run.call_args_list[0].args[0])
        self.assertEqual(["adb", "devices"], run.call_args_list[1].args[0])
        self.assertEqual(["adb", "-s", "raspi", "push"], run.call_args_list[2].args[0][:4])

    def test_sim_deploy_is_available_from_cli(self) -> None:
        with mock.patch("scripts.agp_lib.cli.run_deploy_command", return_value=0) as run_deploy:
            result = main(["sim", "env", "deploy", "--host", "ec2-test"])

        self.assertEqual(0, result)
        run_deploy.assert_called_once_with(
            "sim",
            artifacts_dir=None,
            host="ec2-test",
        )

    def test_sim_vm_commands_are_available_from_cli(self) -> None:
        cases = [
            (["sim", "boot", "--host", "ec2-test", "--instance-id", "i-test", "--region", "ap-test-1"], "start"),
            (["sim", "shutdown", "--host", "ec2-test"], "stop"),
            (["sim", "status", "--host", "ec2-test"], "status"),
        ]

        for argv, ec2_command in cases:
            with self.subTest(argv=argv):
                with mock.patch("scripts.agp_lib.cli.run_ec2_command", return_value=0) as run_ec2:
                    result = main(argv)

                self.assertEqual(0, result)
                run_ec2.assert_called_once()
                self.assertEqual(ec2_command, run_ec2.call_args.args[0])
                self.assertEqual("ec2-test", run_ec2.call_args.kwargs["host"])

    def test_native_deploy_is_available_from_cli(self) -> None:
        with mock.patch("scripts.agp_lib.cli.run_deploy_command", return_value=0) as run_deploy:
            result = main(["native", "deploy", "--serial", "raspi"])

        self.assertEqual(0, result)
        run_deploy.assert_called_once_with(
            "native",
            artifacts_dir=None,
            serial="raspi",
            host=None,
            dest="/home/user",
        )

    def test_native_deploy_passes_host_for_ssh_provider(self) -> None:
        with mock.patch("scripts.agp_lib.cli.run_deploy_command", return_value=0) as run_deploy:
            result = main(["native", "deploy", "--host", "raspi-net"])

        self.assertEqual(0, result)
        run_deploy.assert_called_once_with(
            "native",
            artifacts_dir=None,
            serial=None,
            host="raspi-net",
            dest="/home/user",
        )

    def test_native_deploy_uses_scp_when_ssh_provider_is_selected(self) -> None:
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

            config = {"selected_providers": {"device": "ssh_scp"}}
            with (
                mock.patch("scripts.agp_lib._deploy.load_config", return_value=config),
                mock.patch("scripts.agp_lib._deploy.subprocess.run") as run,
            ):
                run.return_value.returncode = 0

                result = run_deploy_command(
                    "native",
                    artifacts_dir=str(root),
                    host="raspi-net",
                    dest="/home/user",
                )

        self.assertEqual(0, result)
        self.assertEqual(2, run.call_count)
        copy_argv = run.call_args_list[0].args[0]
        chmod_argv = run.call_args_list[1].args[0]
        self.assertEqual("scp", copy_argv[0])
        self.assertEqual("raspi-net:/home/user/sensor_demo", copy_argv[-1])
        self.assertEqual(["ssh", "-F"], chmod_argv[:2])
        self.assertEqual(
            ["raspi-net", "chmod 0755 /home/user/sensor_demo"],
            chmod_argv[-2:],
        )

    def test_native_deploy_with_ssh_provider_requires_host(self) -> None:
        config = {"selected_providers": {"device": "ssh_scp"}}
        with (
            mock.patch("scripts.agp_lib._deploy.load_config", return_value=config),
            mock.patch("scripts.agp_lib._deploy.subprocess.run") as run,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            result = run_deploy_command(
                "native",
                artifacts_dir=str(Path(__file__).parent),
                dest="/home/user",
            )

        self.assertNotEqual(0, result)
        run.assert_not_called()

    def test_native_fetch_copies_manifest_sources_from_codespace(self) -> None:
        manifest = {
            "name": "sensor-demo",
            "deploy": {
                "sim": {
                    "files": [
                        {"src": "files/cuse_i2c", "dest": "~/cuse_i2c", "mode": "0755"},
                        {"src": "files/web-bridge", "dest": "~/web-bridge"},
                    ]
                },
                "native": {
                    "files": [
                        {"src": "files/sensor_demo", "dest": "/home/user/sensor_demo", "mode": "0755"}
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
                mock.patch("scripts.agp_lib._deploy.select_codespace", return_value="codespace-test"),
                mock.patch("scripts.agp_lib._deploy.gh_codespace_cp", side_effect=fake_cp) as cp,
            ):
                result = fetch_codespace_artifacts(root, remote_root="/workspaces/out")

            written_manifest = json.loads((root / "artifact.json").read_text(encoding="utf-8"))

        self.assertEqual(0, result)
        self.assertEqual(manifest, written_manifest)
        self.assertEqual(4, cp.call_count)

    def test_native_sync_fetches_then_deploys(self) -> None:
        with (
            mock.patch("scripts.agp_lib._deploy.fetch_codespace_artifacts", return_value=0) as fetch,
            mock.patch("scripts.agp_lib._deploy.run_deploy_command", return_value=0) as deploy,
        ):
            result = run_native_sync_command(
                artifacts_dir=str(Path("/tmp/agp-artifacts")),
                codespace="codespace-test",
                remote_root="/workspaces/out",
                serial="raspi",
                dest="/home/user",
            )

        self.assertEqual(0, result)
        fetch.assert_called_once()
        deploy.assert_called_once_with(
            "native",
            artifacts_dir=str(Path("/tmp/agp-artifacts").resolve()),
            serial="raspi",
            host=None,
            dest="/home/user",
        )

    def test_native_fetch_is_available_from_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("scripts.agp_lib.cli.fetch_codespace_artifacts", return_value=0) as fetch:
                result = main(
                    [
                        "native",
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

    def test_native_sync_is_available_from_cli(self) -> None:
        with mock.patch("scripts.agp_lib.cli.run_native_sync_command", return_value=0) as sync:
            result = main(
                [
                    "native",
                    "sync",
                    "--codespace",
                    "codespace-test",
                    "--remote-root",
                    "/workspaces/out",
                    "--serial",
                    "raspi",
                    "--dest",
                    "/home/user",
                ]
            )

        self.assertEqual(0, result)
        sync.assert_called_once_with(
            artifacts_dir=None,
            codespace="codespace-test",
            remote_root="/workspaces/out",
            serial="raspi",
            host=None,
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
                mock.patch("scripts.agp_lib._code.Path.home", return_value=home),
                mock.patch("scripts.agp_lib._code.shutil.which", return_value="/usr/bin/tool"),
                mock.patch("scripts.agp_lib._code.subprocess.run", side_effect=run_side_effect),
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
            self.assertIn(f"CODESPACE_MOUNT_DIR='{cwd / 'codespaces'}'", state)
            terminal = home / ".local" / "bin" / "codespace-terminal"
            self.assertIn("Run: agp code start", terminal.read_text(encoding="utf-8"))
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
                mock.patch("scripts.agp_lib._code.Path.home", return_value=home),
                mock.patch("scripts.agp_lib._code.shutil.which", return_value="/usr/bin/tool"),
                mock.patch("scripts.agp_lib._code.subprocess.run", side_effect=run_side_effect),
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
                mock.patch("scripts.agp_lib._code.Path.home", return_value=home),
                mock.patch("scripts.agp_lib._code.shutil.which", return_value="/usr/bin/tool"),
                mock.patch("scripts.agp_lib._code.subprocess.run", side_effect=run_side_effect) as run,
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
                mock.patch("scripts.agp_lib._code.Path.home", return_value=home),
                mock.patch("scripts.agp_lib._code.shutil.which", return_value="/usr/bin/tool"),
                mock.patch("scripts.agp_lib._code.subprocess.run", side_effect=run_side_effect) as run,
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
                    "env",
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
            json_output=False,
        )

    def test_sim_cli_omits_host_by_default(self) -> None:
        with mock.patch("scripts.agp_lib.cli.run_sim_command", return_value=0) as run_sim:
            result = main(["sim", "env", "start"])

        self.assertEqual(0, result)
        run_sim.assert_called_once_with(
            "start",
            host=None,
            settings=None,
            profile_name=None,
            port_forward=True,
            stop_port_forward=True,
            json_output=False,
        )

    def test_sim_status_is_available_from_cli(self) -> None:
        with mock.patch("scripts.agp_lib.cli.run_sim_command", return_value=0) as run_sim:
            result = main(["sim", "env", "status", "--host", "ec2-test"])

        self.assertEqual(0, result)
        run_sim.assert_called_once_with(
            "status",
            host="ec2-test",
            settings=None,
            profile_name=None,
            port_forward=True,
            stop_port_forward=True,
            json_output=False,
        )

    def test_setup_can_store_default_ec2_host(self) -> None:
        providers = [DevelopmentProvider]
        config = {"selected_providers": {}}

        with (
            mock.patch("scripts.agp_lib._setup.discover_environment_providers", return_value=providers),
            mock.patch("scripts.agp_lib._setup.load_config", return_value=config),
            mock.patch("scripts.agp_lib._setup.save_config") as save_config,
            mock.patch("scripts.agp_lib._setup.installed_vscode_terminal_bridge_path", return_value=None),
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

            with mock.patch("scripts.agp_lib._config.CONFIG_PATH", config_path):
                config = load_config()

        self.assertEqual("wsl", config["selected_providers"]["development"])
        self.assertEqual("vibecode-graviton", config["ec2"]["host"])

    def test_load_config_warns_on_invalid_json(self) -> None:
        from scripts.agp_lib.cli import default_config

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / ".agp" / "config.json"
            config_path.parent.mkdir()
            config_path.write_text("{ not json", encoding="utf-8")

            stderr = io.StringIO()
            with (
                mock.patch("scripts.agp_lib._config.CONFIG_PATH", config_path),
                contextlib.redirect_stderr(stderr),
            ):
                config = load_config()

        self.assertEqual(default_config(), config)
        self.assertIn("not valid JSON", stderr.getvalue())

    def test_save_config_is_atomic_and_leaves_no_temp_file(self) -> None:
        from scripts.agp_lib.cli import save_config

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / ".agp" / "config.json"

            with mock.patch("scripts.agp_lib._config.CONFIG_PATH", config_path):
                save_config({"selected_providers": {"device": "ssh_scp"}})

            self.assertTrue(config_path.is_file())
            data = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual({"device": "ssh_scp"}, data["selected_providers"])

            leftovers = [
                path
                for path in config_path.parent.iterdir()
                if path.name != config_path.name
            ]
            self.assertEqual([], leftovers)

    def test_project_root_points_to_repository_root(self) -> None:
        """PROJECT_ROOT must resolve to the repo root, not scripts/."""
        from scripts.agp_lib.cli import PROJECT_ROOT

        self.assertTrue(
            (PROJECT_ROOT / "AGENT.md").is_file(),
            f"PROJECT_ROOT={PROJECT_ROOT} is not the repository root "
            "(AGENT.md not found at expected location).",
        )
        self.assertTrue((PROJECT_ROOT / "scripts" / "agp_lib").is_dir())

    def test_deploy_rejects_invalid_mode_in_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "files").mkdir()
            (root / "files" / "x").write_text("", encoding="utf-8")
            (root / "artifact.json").write_text(
                json.dumps(
                    {
                        "name": "bad-mode",
                        "deploy": {
                            "sim": {
                                "files": [
                                    {
                                        "src": "files/x",
                                        "dest": "~/x",
                                        "mode": "rwx",  # invalid: not octal
                                    }
                                ]
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            config = {"selected_providers": {}, "ec2": {"host": "h"}}
            with (
                mock.patch("scripts.agp_lib._deploy.load_config", return_value=config),
                mock.patch("scripts.agp_lib._deploy.subprocess.run") as run,
                contextlib.redirect_stderr(io.StringIO()),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = run_deploy_command("sim", artifacts_dir=str(root))

            self.assertNotEqual(0, result)
            run.assert_not_called()

    def test_terminal_gc_removes_old_processed_requests(self) -> None:
        from scripts.agp_lib.cli import run_terminal_gc

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            processed = tmp_path / ".agp" / "terminal-requests" / "processed"
            status_dir = tmp_path / ".agp" / "terminal-status"
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
                    "scripts.agp_lib._terminal.CONFIG_PATH",
                    tmp_path / ".agp" / "config.json",
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

    def test_gpio_sim_check_json_outputs_machine_readable_payload(self) -> None:
        completed = mock.Mock(
            returncode=0,
            stdout=(
                "@@KERNEL@@\n"
                "6.8.0-test\n"
                "@@MODINFO@@\n"
                "0\n"
                "modinfo: ERROR: Module gpio-sim not found.\n"
                "@@CONFIG@@\n"
                "CONFIG_GPIO_SIM=(not found)\n"
                "@@CONFIGFS@@\n"
                "1\n"
                "@@DEV@@\n"
            ),
            stderr="",
        )
        with (
            mock.patch("scripts.agp_lib.environments.registry.simulation.ssh_remote.SshRemoteEnvironment.run_remote", return_value=completed) as run,
            mock.patch("scripts.agp_lib._sim._get_sim_provider", return_value=SshRemoteEnvironment),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_gpio_sim_check("ec2-test", json_output=True)

        self.assertEqual(1, result)
        self.assertIn("gpio-sim", run.call_args.args[1])
        payload = json.loads(output.getvalue())
        self.assertEqual("ec2-test", payload["host"])
        self.assertEqual("6.8.0-test", payload["kernel"])
        self.assertFalse(payload["module_available"])
        self.assertFalse(payload["ok"])

    def test_sim_gpio_status_json_outputs_machine_readable_payload(self) -> None:
        completed = mock.Mock(
            returncode=0,
            stdout=(
                "@@SERVICE@@\n"
                "active\n"
                "@@DEVICE@@\n"
                "/dev/gpiochip0 1\n"
                "@@MOUNT@@\n"
                "0\n"
                "@@CONFIGFS@@\n"
                "1\n"
                "1\n"
                "gpiochip0\n"
                "@@GPIOCHIPS@@\n"
                "/dev/gpiochip0\n"
            ),
            stderr="",
        )
        with (
            mock.patch("scripts.agp_lib.environments.registry.simulation.ssh_remote.SshRemoteEnvironment.run_remote", return_value=completed) as run,
            mock.patch("scripts.agp_lib._sim._get_sim_provider", return_value=SshRemoteEnvironment),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_sim_gpio_command("status", host="ec2-test", json_output=True)

        self.assertEqual(0, result)
        self.assertIn("@@SERVICE@@", run.call_args.args[1])
        payload = json.loads(output.getvalue())
        self.assertEqual("ec2-test", payload["host"])
        self.assertTrue(payload["ok"])
        self.assertEqual("gpiochip0", payload["configfs"]["chip_name"])

    def test_sim_diag_json_outputs_machine_readable_payload(self) -> None:
        completed = mock.Mock(
            returncode=0,
            stdout=(
                "@@PROC@@\n"
                "1234 bridge.py\n"
                "@@DEV@@\n"
                "/dev/i2c-1 1\n"
                "/dev/gpiochip0 0\n"
                "/dev/spidev0.0 0\n"
                "@@API@@\n"
                '{"led18": 1}\n'
            ),
            stderr="",
        )
        with (
            mock.patch("scripts.agp_lib._sim.load_config", return_value={"selected_providers": {}, "ec2": {"host": "ec2-test"}}),
            mock.patch("scripts.agp_lib.environments.registry.simulation.ssh_remote.SshRemoteEnvironment.run_remote", return_value=completed) as run,
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_sim_command("diag", json_output=True)

        self.assertEqual(0, result)
        self.assertIn("@@PROC@@", run.call_args.args[1])
        payload = json.loads(output.getvalue())
        self.assertEqual("ec2-test", payload["host"])
        self.assertTrue(payload["ok"])
        self.assertEqual({"led18": 1}, payload["api"])

    def test_gpio_sim_check_json_is_available_from_cli(self) -> None:
        with mock.patch("scripts.agp_lib.cli.run_sim_command", return_value=0) as run_sim:
            result = main(["sim", "env", "gpio-sim-check", "--json", "--host", "ec2-test"])

        self.assertEqual(0, result)
        run_sim.assert_called_once_with(
            "gpio-sim-check",
            host="ec2-test",
            settings=None,
            profile_name=None,
            port_forward=True,
            stop_port_forward=True,
            json_output=True,
        )

    def test_sim_gpio_start_is_available_from_cli(self) -> None:
        with mock.patch("scripts.agp_lib.cli.run_sim_gpio_command", return_value=0) as run_gpio:
            result = main(["sim", "gpio", "start", "--host", "ec2-test"])

        self.assertEqual(0, result)
        run_gpio.assert_called_once_with("start", host="ec2-test", json_output=False)

    def test_sim_gpio_plan_json_is_available_from_cli(self) -> None:
        with mock.patch("scripts.agp_lib.cli.run_sim_gpio_command", return_value=0) as run_gpio:
            result = main(["sim", "gpio", "plan", "--json"])

        self.assertEqual(0, result)
        run_gpio.assert_called_once_with("plan", host=None, json_output=True)

    def test_sim_diag_json_is_available_from_cli(self) -> None:
        with mock.patch("scripts.agp_lib.cli.run_sim_command", return_value=0) as run_sim:
            result = main(["sim", "env", "diag", "--json", "--host", "ec2-test"])

        self.assertEqual(0, result)
        run_sim.assert_called_once_with(
            "diag",
            host="ec2-test",
            settings=None,
            profile_name=None,
            port_forward=True,
            stop_port_forward=True,
            json_output=True,
        )


class SimPanelTests(unittest.TestCase):
    def test_build_panel_command_button_press(self) -> None:
        command = LinuxSimCommandBuilder().build_panel("button-press", {"line": 17, "duration_ms": 150})
        self.assertIn("/api/button/press?line=17&duration_ms=150", command)
        self.assertIn("-X POST", command)

    def test_build_panel_command_rfid_tap_encodes_uid(self) -> None:
        command = LinuxSimCommandBuilder().build_panel("rfid-tap", {"uid": "04:AB:CD:EF:01:23"})
        self.assertIn("/api/rfid/tap?uid=04:AB:CD:EF:01:23", command)

    def test_build_panel_command_state_is_get(self) -> None:
        command = LinuxSimCommandBuilder().build_panel("state", {})
        self.assertIn("/api/state", command)
        self.assertNotIn("-X POST", command)

    def test_build_panel_command_rejects_unknown_action(self) -> None:
        with self.assertRaises(ValueError):
            LinuxSimCommandBuilder().build_panel("explode", {})

    def test_run_sim_panel_sshes_with_curl(self) -> None:
        completed = mock.Mock(returncode=0)
        with (
            mock.patch("scripts.agp_lib._sim.load_config", return_value={"ec2": {"host": "ec2-test"}}),
            mock.patch("scripts.agp_lib.environments.registry.simulation.ssh_remote.SshRemoteEnvironment.run_remote", return_value=completed) as run,
        ):
            result = run_sim_panel("button-press", host="ec2-test", line=17, duration_ms=150)

        self.assertEqual(0, result)
        self.assertEqual("ec2-test", run.call_args.args[0])
        self.assertIn("/api/button/press?line=17&duration_ms=150", run.call_args.args[1])

    def test_run_sim_panel_state_pretty_prints_json(self) -> None:
        completed = mock.Mock(returncode=0, stdout='{"led18": 1}', stderr="")
        with (
            mock.patch("scripts.agp_lib._sim.load_config", return_value={"ec2": {"host": "ec2-test"}}),
            mock.patch("scripts.agp_lib.environments.registry.simulation.ssh_remote.SshRemoteEnvironment.run_remote", return_value=completed),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_sim_panel("state", host="ec2-test")

        self.assertEqual(0, result)
        self.assertEqual({"led18": 1}, json.loads(output.getvalue()))

    def test_sim_button_press_is_available_from_cli(self) -> None:
        with mock.patch("scripts.agp_lib.cli.run_sim_panel", return_value=0) as run_panel:
            result = main(["sim", "ui", "button", "press", "17", "--host", "ec2-test"])

        self.assertEqual(0, result)
        run_panel.assert_called_once_with(
            "button-press",
            host="ec2-test",
            line=17,
            duration_ms=150,
        )

    def test_sim_rfid_tap_is_available_from_cli(self) -> None:
        with mock.patch("scripts.agp_lib.cli.run_sim_panel", return_value=0) as run_panel:
            result = main(["sim", "ui", "rfid", "tap", "04:AB:CD:EF:01:23", "--host", "ec2-test"])

        self.assertEqual(0, result)
        run_panel.assert_called_once_with(
            "rfid-tap",
            host="ec2-test",
            uid="04:AB:CD:EF:01:23",
        )

    def test_sim_env_status_json_is_available_from_cli(self) -> None:
        with mock.patch("scripts.agp_lib.cli.run_sim_command", return_value=0) as run_sim:
            result = main(["sim", "env", "status", "--json", "--host", "ec2-test"])

        self.assertEqual(0, result)
        run_sim.assert_called_once_with(
            "status",
            host="ec2-test",
            settings=None,
            profile_name=None,
            port_forward=True,
            stop_port_forward=True,
            json_output=True,
        )

    def test_hw_init_creates_empty_csv_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hw_dir = Path(tmp) / "hardware"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(["hw", "init", "--dir", str(hw_dir)])

            self.assertEqual(0, result)
            self.assertEqual(
                "component_id,name,kind,part_number,description\n",
                (hw_dir / "components.csv").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                "name,chip,line,direction,role,active,initial,pull,sim_control,description\n",
                (hw_dir / "gpio.csv").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                "name,bus,dev,address,driver,sim,description\n",
                (hw_dir / "i2c.csv").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                "name,bus,chip_select,dev,mode,max_speed_hz,driver,sim,description\n",
                (hw_dir / "spi.csv").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                "source,source_pin,target,target_pin,signal,description\n",
                (hw_dir / "connections.csv").read_text(encoding="utf-8"),
            )

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
        with mock.patch("scripts.agp_lib.cli.run_hw_command", return_value=0) as run_hw:
            result = main(["hw", "init", "--dir", "custom-hw", "--force"])

        self.assertEqual(0, result)
        run_hw.assert_called_once_with(
            "init",
            output_dir="custom-hw",
            force=True,
        )


if __name__ == "__main__":
    unittest.main()
