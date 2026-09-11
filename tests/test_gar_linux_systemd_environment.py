from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.gar_lib.access.channel import AccessResult
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.simulation.runtime.linux_commands import LinuxSystemdCommandBuilder
from scripts.gar_lib.simulation.runtime.linux_systemd import LinuxSystemdSimulationEnvironment


class GarLinuxSystemdEnvironmentTest(unittest.TestCase):
    def test_configure_system_env_writes_deterministic_root_owned_file(self) -> None:
        commands = mock.Mock()
        commands.run.return_value = AccessResult(("channel",), 0)
        files = mock.Mock()

        def capture(source: Path, destination: str) -> AccessResult:
            self.assertEqual("ALPHA=one\nBETA=two\n", source.read_text(encoding="utf-8"))
            self.assertTrue(source.is_file())
            self.assertEqual("/tmp/gar-system-env-", destination[:20])
            return AccessResult(("channel",), 0)

        files.push.side_effect = capture
        environment = LinuxSystemdSimulationEnvironment(commands, files, mock.Mock())

        destination = environment.configure_system_env("demo-app", {"BETA": "two", "ALPHA": "one"})

        self.assertEqual("/etc/gar/system/demo-app.env", destination)
        install = commands.run.call_args.args[0]
        self.assertIn("sudo mkdir -p", install)
        self.assertIn("sudo cp", install)
        self.assertIn("sudo chmod 0644", install)
        self.assertIn("sudo mv -f", install)
        self.assertIn("/etc/gar/system/demo-app.env.gar-new", install)
        self.assertNotIn("/etc/gar/demo-app.env", install)

    def test_configure_system_env_rejects_unsafe_input_before_transfer(self) -> None:
        commands = mock.Mock()
        files = mock.Mock()
        environment = LinuxSystemdSimulationEnvironment(commands, files, mock.Mock())

        for application, values in (
            ("../demo", {"SAFE": "value"}),
            ("demo", {"NOT-VALID": "value"}),
            ("demo", {"SAFE": "line\nbreak"}),
            ("demo", {"SAFE": "nul\x00value"}),
        ):
            with self.subTest(application=application, values=values):
                with self.assertRaises(GarDomainError):
                    environment.configure_system_env(application, values)

        files.push.assert_not_called()
        commands.run.assert_not_called()

    def test_deploy_uses_injected_channels_without_knowing_ssh_or_adb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "files" / "app"
            source.parent.mkdir()
            source.write_text("app", encoding="utf-8")
            (root / "artifact.json").write_text(
                json.dumps({"deploy": {"app": {"files": [{"src": "files/app", "dest": "~/app", "mode": "0755"}]}}}),
                encoding="utf-8",
            )
            workspace = Workspace("ws", "Local/App", "App", {"type": "local", "path": tmp})
            artifact = Artifact(ArtifactKind.SIM_APP, workspace, root)
            commands = mock.Mock()
            commands.run.return_value = AccessResult(("channel",), 0)
            files = mock.Mock()
            files.push.return_value = AccessResult(("channel",), 0)
            builder = mock.Mock()

            LinuxSystemdSimulationEnvironment(commands, files, builder).deploy(artifact)

        files.push.assert_called_once()
        install = commands.run.call_args_list[1].args[0]
        self.assertIn('mkdir -p $(dirname "${HOME}"/', install)
        self.assertNotIn("sudo", install)
        self.assertIn("chmod 0755", install)
        self.assertIn("mv -f", install)

    def test_runtime_artifact_maps_system_destinations(self) -> None:
        command = LinuxSystemdSimulationEnvironment._install_command(
            "/tmp/cuse_i2c",
            "/usr/local/sbin/cuse_i2c",
            source_is_dir=False,
            mode="0755",
        )

        self.assertIn("sudo cp", command)
        self.assertIn("/usr/local/sbin/cuse_i2c", command)
        self.assertIn("/usr/local/sbin/cuse_i2c.gar-new", command)
        self.assertIn("sudo mv -f", command)
        self.assertIn("trap 'rm -rf -- /tmp/cuse_i2c' EXIT", command)

    def test_runtime_deploy_stops_running_services_before_replacing_binaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "files" / "cuse_spi"
            source.parent.mkdir()
            source.write_text("binary", encoding="utf-8")
            (root / "artifact.json").write_text(
                json.dumps({"deploy": {"sim_env": {"files": [{"src": "files/cuse_spi", "dest": "~/cuse_spi"}]}}}),
                encoding="utf-8",
            )
            workspace = Workspace("ws", "Local/App", "App", {"type": "local", "path": tmp})
            artifact = Artifact(ArtifactKind.SIM_RUNTIME, workspace, root)
            commands = mock.Mock()
            commands.run.return_value = AccessResult(("channel",), 0)
            files = mock.Mock()
            files.push.return_value = AccessResult(("channel",), 0)

            LinuxSystemdSimulationEnvironment(commands, files, mock.Mock()).deploy(artifact)

        self.assertIn("systemctl stop gar-sim.target", commands.run.call_args_list[0].args[0])

    def test_lifecycle_uses_command_builder_and_injected_channel(self) -> None:
        commands = mock.Mock()
        commands.run.return_value = AccessResult(("channel",), 0, "running\n", "")
        builder = mock.Mock()
        builder.build_sim_start.return_value = "systemctl start gar-sim.target"
        environment = LinuxSystemdSimulationEnvironment(commands, mock.Mock(), builder)

        result = environment.start({"gpio": []})

        self.assertEqual(0, result)
        builder.build_sim_start.assert_called_once_with({"gpio": []})
        commands.run.assert_called_once_with("systemctl start gar-sim.target")

    def test_diag_returns_structured_result_without_printing_channel_output(self) -> None:
        commands = mock.Mock()
        commands.run.return_value = AccessResult(
            ("channel",),
            0,
            '@@PROC@@\n123 bridge.py\n@@DEV@@\n/dev/i2c-1 1\n@@API@@\n{"ready": true}\n',
            "",
        )
        builder = mock.Mock()
        builder.build_sim_diag_json.return_value = "diagnose"
        environment = LinuxSystemdSimulationEnvironment(commands, mock.Mock(), builder)

        diagnostic = environment.diag({"i2c": []})

        self.assertTrue(diagnostic.ok)
        self.assertEqual([{"pid": 123, "cmd": "bridge.py"}], diagnostic.processes)
        self.assertEqual({"/dev/i2c-1": True}, diagnostic.devices)
        self.assertEqual({"ready": True}, diagnostic.api)
        commands.run.assert_called_once_with("diagnose")

    def test_diag_preserves_command_failure_as_structured_result(self) -> None:
        commands = mock.Mock()
        commands.run.return_value = AccessResult(("channel",), 7, "", "not running\n")
        builder = mock.Mock()
        builder.build_sim_diag_json.return_value = "diagnose"
        environment = LinuxSystemdSimulationEnvironment(commands, mock.Mock(), builder)

        diagnostic = environment.diag({})

        self.assertFalse(diagnostic.ok)
        self.assertEqual(1, diagnostic.exit_code)
        self.assertEqual("diagnostic command exited 7", diagnostic.error)
        self.assertEqual("not running", diagnostic.stderr)


class LinuxSystemdCommandBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = LinuxSystemdCommandBuilder()
        self.hardware: dict[str, list[dict[str, str]]] = {
            "gpio": [],
            "i2c": [],
            "spi": [],
        }

    def test_generated_install_script_uses_one_gar_runtime_directory(self) -> None:
        command = self.builder.build_systemd_install(self.hardware)

        self.assertIn("RuntimeDirectory=gar", command)
        self.assertNotIn("RuntimeDirectory=Gapless Agent Runtime", command)
        self.assertIn("sudo rm -f /etc/gar/hardware/*.csv", command)
        self.assertIn(
            "PassEnvironment=GAR_BRIDGE_HOST GAR_BRIDGE_PORT GAR_BRIDGE_ALLOWED_HOSTS",
            command,
        )
        self.assertIn("GAR_METRICS_DIR=/run/gar/metrics", command)
        self.assertIn("mkdir -p /run/gar/metrics", command)

    def test_bridge_prefers_bundled_venv_before_system_python(self) -> None:
        command = self.builder.build_systemd_install(self.hardware)

        bundled_python = '"/usr/local/lib/gar/venv/bin/python3"'
        system_python = '"/usr/bin/python3"'
        self.assertIn("${GAR_BRIDGE_PYTHON:-}", command)
        self.assertIn("import aiohttp", command)
        self.assertLess(command.index(bundled_python), command.index(system_python))

    def test_lifecycle_scripts_are_fail_fast_and_do_not_kill_by_process_name(self) -> None:
        start = self.builder.build_systemd_start(self.hardware)
        stop = self.builder.build_systemd_stop(self.hardware)

        self.assertTrue(start.startswith("set -eu\n"))
        self.assertTrue(stop.startswith("set -eu\n"))
        self.assertNotIn("pkill", start)
        self.assertNotIn("pkill", stop)
        self.assertIn("systemctl is-active", start)

    def test_process_probe_cannot_match_its_own_literal_pattern(self) -> None:
        command = self.builder.build_sim_diag_json(self.hardware)

        self.assertIn("[b]ridge.py|[c]use_i2c|[c]use_spi", command)
        self.assertNotIn('pgrep -af "bridge.py|cuse_i2c|cuse_spi"', command)

    def test_bridge_requests_fail_on_http_errors_and_have_timeouts(self) -> None:
        command = self.builder.build_io("state", {})

        self.assertIn("--fail", command)
        self.assertIn("--connect-timeout 2", command)
        self.assertIn("--max-time 5", command)

    def test_runtime_starts_only_declared_bus_simulators(self) -> None:
        hardware = {
            "gpio": [
                {"name": "lcd_dc", "line": "23", "direction": "output", "role": "display_ctrl"},
            ],
            "i2c": [
                {"name": "camera_ctrl", "dev": "/dev/i2c-3", "driver": "sc3336", "sim": ""},
            ],
            "spi": [
                {
                    "name": "ili9341_lcd",
                    "dev": "/dev/spidev0.0",
                    "driver": "ili9341",
                    "sim": "ili9341",
                },
            ],
        }

        command = self.builder.build_systemd_install(hardware)

        self.assertIn("ExecStart=/usr/local/sbin/cuse_spi -f --devname=%i --dc-line=23", command)
        self.assertIn(
            "Wants=gar-gpio-sim.service gar-bridge.service gar-cuse-spi@spidev0.0.service",
            command,
        )
        self.assertNotIn("Wants=gar-gpio-sim.service gar-bridge.service gar-cuse-i2c@i2c-3.service", command)

    def test_physical_spi_driver_does_not_enable_simulator_options(self) -> None:
        hardware = {
            "gpio": [
                {"name": "lcd_dc", "line": "23", "direction": "output", "role": "display_ctrl"},
            ],
            "i2c": [],
            "spi": [
                {
                    "name": "ili9341_lcd",
                    "dev": "/dev/spidev0.0",
                    "driver": "ili9341",
                    "sim": "",
                },
            ],
        }

        command = self.builder.build_systemd_install(hardware)

        self.assertNotIn("gar-cuse-spi@spidev0.0.service", command)
        self.assertNotIn("--dc-line=23", command)
