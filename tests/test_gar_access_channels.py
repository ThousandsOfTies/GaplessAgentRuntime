from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.gar_lib.access.adb import AdbFileChannel, AdbShellChannel
from scripts.gar_lib.access.process import LocalProcessChannel
from scripts.gar_lib.access.serial import SerialArtifactInstaller, SerialConsoleChannel
from scripts.gar_lib.access.ssh import ScpFileChannel, SshCommandChannel
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.errors import AccessConnectionError
from scripts.gar_lib.core.workspace import Workspace


class GarAccessChannelsTest(unittest.TestCase):
    def test_local_process_channel_launches_without_wokwi_specific_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "runtime.log"
            process = mock.Mock(pid=1234)
            with mock.patch(
                "scripts.gar_lib.access.process.subprocess.Popen", return_value=process
            ) as popen:
                result = LocalProcessChannel().start(
                    ("simulator", "--project", str(root)),
                    cwd=root,
                    log_path=log_path,
                )

        self.assertEqual(1234, result.pid)
        self.assertEqual(("simulator", "--project", str(root)), result.argv)
        self.assertEqual(root, popen.call_args.kwargs["cwd"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_ssh_command_channel_returns_structured_result(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "hello\n", "")
        with mock.patch("scripts.gar_lib.access.ssh.subprocess.run", return_value=completed) as run:
            result = SshCommandChannel("sim-host", config_path=Path("/tmp/ssh-config")).run("uname -a")

        self.assertEqual(0, result.returncode)
        self.assertEqual("hello\n", result.stdout)
        self.assertEqual("ssh", result.argv[0])
        self.assertIn("sim-host", result.argv)
        run.assert_called_once()

    def test_ssh_connection_failure_is_not_rendered_by_channel(self) -> None:
        completed = subprocess.CompletedProcess([], 255, "", "Connection timed out")
        with mock.patch("scripts.gar_lib.access.ssh.subprocess.run", return_value=completed):
            with self.assertRaises(AccessConnectionError) as raised:
                SshCommandChannel("sim-host").run("true")

        self.assertEqual("ssh", raised.exception.channel)
        self.assertEqual("sim-host", raised.exception.endpoint)

    def test_ssh_channel_classifies_host_key_failure(self) -> None:
        completed = subprocess.CompletedProcess([], 255, "", "Host key verification failed.")
        with mock.patch("scripts.gar_lib.access.ssh.subprocess.run", return_value=completed):
            with self.assertRaises(AccessConnectionError) as raised:
                SshCommandChannel("sim-host").run("true")

        self.assertEqual("host_key_verification", raised.exception.reason)

    def test_scp_file_channel_builds_push_and_pull_commands(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "", "")
        channel = ScpFileChannel("sim-host", config_path=Path("/tmp/ssh-config"))
        with mock.patch("scripts.gar_lib.access.ssh.subprocess.run", return_value=completed) as run:
            channel.push(Path("/tmp/app"), "/tmp/app")
            channel.pull("/tmp/log", Path("/tmp/log"))

        self.assertEqual("sim-host:/tmp/app", run.call_args_list[0].args[0][-1])
        self.assertEqual("sim-host:/tmp/log", run.call_args_list[1].args[0][-2])

    def test_adb_channels_keep_shell_and_file_capabilities_separate(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "ok", "")
        with mock.patch("scripts.gar_lib.access.adb.subprocess.run", return_value=completed) as run:
            AdbShellChannel("device-1").run("getprop")
            AdbFileChannel("device-1").push(Path("/tmp/app"), "/data/local/tmp/app")

        self.assertEqual(("adb", "-s", "device-1", "shell", "getprop"), run.call_args_list[0].args[0])
        self.assertEqual("push", run.call_args_list[1].args[0][3])

    def test_adb_connection_error_is_structured(self) -> None:
        completed = subprocess.CompletedProcess([], 1, "", "error: device offline")
        with mock.patch("scripts.gar_lib.access.adb.subprocess.run", return_value=completed):
            with self.assertRaises(AccessConnectionError) as raised:
                AdbShellChannel("device-1").run("true")

        self.assertEqual("device_offline", raised.exception.reason)

    def test_serial_installer_uses_target_specific_command_builder(self) -> None:
        workspace = Workspace(
            id="ws",
            name="Local/Product",
            branch="Product",
            connection={"type": "local", "path": "/tmp/product"},
        )
        artifact = Artifact(ArtifactKind.TARGET_APP, workspace, Path("/tmp/artifact"))
        completed = subprocess.CompletedProcess([], 0, "flashed", "")
        installer = SerialArtifactInstaller(lambda item: ["flash-tool", str(item.bundle_path)])
        with mock.patch("scripts.gar_lib.access.serial.subprocess.run", return_value=completed) as run:
            result = installer.install(artifact)

        self.assertEqual("flashed", result.stdout)
        run.assert_called_once_with(
            ("flash-tool", "/tmp/artifact"),
            check=False,
            capture_output=True,
            text=True,
        )

    def test_serial_console_returns_process_session(self) -> None:
        process = mock.Mock()
        with mock.patch("scripts.gar_lib.access.serial.subprocess.Popen", return_value=process) as popen:
            session = SerialConsoleChannel("/dev/ttyUSB0", baud=921600).open()

        self.assertIs(process, session.process)
        popen.assert_called_once_with(("picocom", "--baud", "921600", "/dev/ttyUSB0"))
