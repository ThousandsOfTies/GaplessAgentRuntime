from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.gar_lib.environments.base import DevEnvironment
from scripts.gar_lib.environments.discovery import discover_environment_providers
from scripts.gar_lib.environments.registry.codespace.github_codespaces import (
    GitHubCodespacesEnvironment,
)
from scripts.gar_lib.environments.registry.codespace.local import LocalEnvironment
from scripts.gar_lib.environments.registry.simulator.aws_ssm import AwsSsmEnvironment
from scripts.gar_lib.environments.registry.simulator.mujoco import MujocoEnvironment
from scripts.gar_lib.environments.registry.simulator.renode_mcu import (
    RenodeMcuEnvironment,
)
from scripts.gar_lib.environments.registry.simulator.vibe_remote_device import (
    VibeRemoteVirtualDeviceEnvironment,
)
from scripts.gar_lib.environments.registry.simulator.wokwi import WokwiEnvironment
from scripts.gar_lib.environments.registry.target.adb_usb import AdbUsbEnvironment
from scripts.gar_lib.environments.registry.target.esp32_esptool import (
    Esp32EsptoolEnvironment,
)
from scripts.gar_lib.simulation.mujoco import MujocoSimEnvProcessor


class GarDiscoveryTest(unittest.TestCase):
    def test_discovers_registry_providers(self) -> None:
        providers = discover_environment_providers()
        provider_ids = {provider.provider_id for provider in providers}

        self.assertIn("github_codespaces", provider_ids)
        self.assertIn("aws_ssm", provider_ids)
        self.assertIn("ssh_remote", provider_ids)
        self.assertIn("renode_mcu", provider_ids)
        self.assertIn("mujoco", provider_ids)
        self.assertIn("esp32_qemu_firmware", provider_ids)
        self.assertIn("wokwi", provider_ids)
        self.assertIn("vibe_remote_device", provider_ids)
        self.assertIn("local", provider_ids)
        self.assertIn("adb_usb", provider_ids)
        self.assertIn("ssh_scp", provider_ids)
        self.assertIn("esp32_esptool", provider_ids)
        self.assertTrue(
            all(issubclass(provider, DevEnvironment) for provider in providers)
        )

    def test_discovers_provider_categories_from_directories(self) -> None:
        providers = discover_environment_providers()
        categories_by_provider = {
            provider.provider_id: provider.category_id
            for provider in providers
        }

        self.assertEqual(
            "codespace",
            categories_by_provider["github_codespaces"],
        )
        self.assertEqual("simulator", categories_by_provider["aws_ssm"])
        self.assertEqual("simulator", categories_by_provider["renode_mcu"])
        self.assertEqual("simulator", categories_by_provider["mujoco"])
        self.assertEqual("simulator", categories_by_provider["esp32_qemu_firmware"])
        self.assertEqual("simulator", categories_by_provider["wokwi"])
        self.assertEqual("simulator", categories_by_provider["vibe_remote_device"])
        self.assertEqual("target", categories_by_provider["adb_usb"])
        self.assertEqual("target", categories_by_provider["ssh_scp"])
        self.assertEqual("target", categories_by_provider["esp32_esptool"])

    def test_provider_ids_are_unique(self) -> None:
        providers = discover_environment_providers()
        provider_ids = [provider.provider_id for provider in providers]

        self.assertEqual(len(provider_ids), len(set(provider_ids)))

    def test_local_development_provider_is_default_before_github_codespaces(self) -> None:
        providers = discover_environment_providers()
        codespace_provider_ids = [
            provider.provider_id
            for provider in providers
            if provider.category_id == "codespace"
        ]

        self.assertLess(
            codespace_provider_ids.index("local"),
            codespace_provider_ids.index("github_codespaces"),
        )

    def test_local_development_provider_requires_docker(self) -> None:
        self.assertEqual(("docker",), LocalEnvironment.required_commands)

    def test_mujoco_provider_uses_current_python_package(self) -> None:
        with mock.patch(
            "scripts.gar_lib.environments.registry.simulator.mujoco._mujoco_is_importable",
            return_value=True,
        ):
            statuses = MujocoEnvironment.dependency_status()

        self.assertEqual("mujoco-python", statuses[0].name)
        self.assertTrue(statuses[0].installed)

    def test_mujoco_processor_validates_and_starts_a_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = root / "robot.xml"
            workspace = root / "workspace"
            model.write_text("<mujoco model='test'/>", encoding="utf-8")
            completed = subprocess.CompletedProcess([], 0, "", "")
            process = mock.Mock(pid=12345)
            with (
                mock.patch.dict(
                    os.environ,
                    {"GAR_MUJOCO_MODEL": str(model), "GAR_MUJOCO_WORKSPACE": str(workspace)},
                    clear=False,
                ),
                mock.patch("scripts.gar_lib.simulation.mujoco.subprocess.run", return_value=completed),
                mock.patch("scripts.gar_lib.simulation.mujoco.subprocess.Popen", return_value=process) as popen,
                mock.patch.object(MujocoSimEnvProcessor, "_bridge_state", return_value={"ok": True}),
                mock.patch("scripts.gar_lib.simulation.mujoco._is_running", return_value=True),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                provider = MujocoSimEnvProcessor(MujocoEnvironment)
                self.assertEqual(0, provider.build(json_output=True))
                self.assertEqual(0, provider.start({}))
                self.assertEqual(0, provider.status({}, json_output=True))

            self.assertEqual(12345, json.loads((workspace / "state.json").read_text(encoding="utf-8"))["pid"])
            self.assertTrue(any(part.endswith("mujoco_bridge.py") for part in popen.call_args.args[0]))

    def test_vibe_remote_device_uses_node_sh_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            node_sh = Path(tmp) / "node.sh"
            node_sh.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

            with mock.patch.dict(
                "os.environ",
                {"VIBE_REMOTE_NODE_SH": str(node_sh)},
            ):
                statuses = VibeRemoteVirtualDeviceEnvironment.dependency_status()

        self.assertEqual(1, len(statuses))
        self.assertEqual(str(node_sh), statuses[0].name)
        self.assertEqual(str(node_sh), statuses[0].path)

    def test_vibe_remote_device_requires_node_without_node_sh(self) -> None:
        missing_node_sh = Path(tempfile.gettempdir()) / "gar-missing-node.sh"
        with (
            mock.patch.dict(
                "os.environ",
                {"VIBE_REMOTE_NODE_SH": str(missing_node_sh)},
            ),
            mock.patch(
                "scripts.gar_lib.environments.registry.simulator.vibe_remote_device._find_node",
                return_value=None,
            ),
        ):
            statuses = VibeRemoteVirtualDeviceEnvironment.dependency_status()

        self.assertEqual(1, len(statuses))
        self.assertEqual("node", statuses[0].name)
        self.assertIsNone(statuses[0].path)

    def test_wokwi_installer_runs_official_install_script(self) -> None:
        with (
            mock.patch("shutil.which", return_value="/usr/bin/tool"),
            mock.patch.object(WokwiEnvironment, "run_subprocess", return_value=0) as run,
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = WokwiEnvironment.install_dependencies(["wokwi-cli"])

        self.assertEqual(0, result)
        run.assert_called_once_with(["sh", "-c", "curl -L https://wokwi.com/ci/install.sh | sh"])
        self.assertIn("Wokwi CLI をインストールします", output.getvalue())

    def test_wokwi_dependency_status_finds_user_bin_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            cli = home / "bin" / "wokwi-cli"
            cli.parent.mkdir()
            cli.write_text("#!/bin/sh\n", encoding="utf-8")
            cli.chmod(0o755)

            with (
                mock.patch("shutil.which", return_value=None),
                mock.patch("pathlib.Path.home", return_value=home),
            ):
                statuses = WokwiEnvironment.dependency_status()
                missing = WokwiEnvironment.missing_commands()

        self.assertEqual(1, len(statuses))
        self.assertEqual(str(cli), statuses[0].path)
        self.assertEqual([], missing)

    def test_esp32_esptool_dependency_status_finds_project_venv_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cli = root / ".venv" / "bin" / "esptool"
            cli.parent.mkdir(parents=True)
            cli.write_text("#!/bin/sh\n", encoding="utf-8")
            cli.chmod(0o755)

            with (
                mock.patch("shutil.which", return_value=None),
                mock.patch("scripts.gar_lib.environments.registry.target.esp32_esptool.PROJECT_ROOT", root),
            ):
                statuses = Esp32EsptoolEnvironment.dependency_status()
                missing = Esp32EsptoolEnvironment.missing_commands()

        self.assertEqual(1, len(statuses))
        self.assertEqual(str(cli), statuses[0].path)
        self.assertEqual([], missing)

    def test_esp32_esptool_installer_uses_project_venv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            python = root / ".venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("#!/bin/sh\n", encoding="utf-8")

            with (
                mock.patch("scripts.gar_lib.environments.registry.target.esp32_esptool.PROJECT_ROOT", root),
                mock.patch.object(Esp32EsptoolEnvironment, "run_subprocess", return_value=0) as run,
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = Esp32EsptoolEnvironment.install_dependencies(["esptool"])

        self.assertEqual(0, result)
        run.assert_called_once_with([str(python), "-m", "pip", "install", "esptool"])
        self.assertIn("esptool", output.getvalue())

    def test_renode_mcu_requires_renode_and_renode_test(self) -> None:
        self.assertEqual(
            ("renode", "renode-test"),
            RenodeMcuEnvironment.required_commands,
        )

    def test_renode_mcu_installer_writes_globalization_safe_launchers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "renode-real"
            target.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            launcher = root / "renode"

            from scripts.gar_lib.environments.registry.simulator import renode_mcu

            renode_mcu._write_launcher(
                launcher,
                target,
                set_globalization_invariant=True,
            )

            text = launcher.read_text(encoding="utf-8")

        self.assertIn("DOTNET_SYSTEM_GLOBALIZATION_INVARIANT", text)
        self.assertIn(str(target), text)

    def test_github_codespaces_installs_gh_with_apt_get(self) -> None:
        commands: list[list[str]] = []

        def fake_run_subprocess(argv: list[str]) -> int:
            commands.append(argv)
            return 0

        with (
            mock.patch(
                "scripts.gar_lib.environments.registry.codespace.github_codespaces._is_wsl_or_linux",
                return_value=True,
            ),
            mock.patch(
                "scripts.gar_lib.environments.registry.codespace.github_codespaces.shutil.which",
                return_value="/usr/bin/apt-get",
            ),
            mock.patch.object(
                GitHubCodespacesEnvironment,
                "sudo_block_reason",
                return_value=None,
            ),
            mock.patch.object(
                GitHubCodespacesEnvironment,
                "run_subprocess",
                side_effect=fake_run_subprocess,
            ),
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                result = GitHubCodespacesEnvironment.install_dependencies(["gh"])

        self.assertEqual(0, result)
        self.assertEqual(
            [
                ["sudo", "apt-get", "update"],
                ["sudo", "apt-get", "install", "-y", "gh"],
            ],
            commands,
        )

    def test_local_development_provider_installs_docker_with_apt_get(self) -> None:
        commands: list[list[str]] = []

        def fake_run_subprocess(argv: list[str]) -> int:
            commands.append(argv)
            return 0

        with (
            mock.patch(
                "scripts.gar_lib.environments.registry.codespace.local._is_wsl_or_linux",
                return_value=True,
            ),
            mock.patch(
                "scripts.gar_lib.environments.registry.codespace.local.shutil.which",
                return_value="/usr/bin/apt-get",
            ),
            mock.patch.object(
                LocalEnvironment,
                "sudo_block_reason",
                return_value=None,
            ),
            mock.patch.object(
                LocalEnvironment,
                "run_subprocess",
                side_effect=fake_run_subprocess,
            ),
            mock.patch(
                "scripts.gar_lib.environments.registry.codespace.local.getpass.getuser",
                return_value="testuser",
            ),
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                result = LocalEnvironment.install_dependencies(["docker"])

        self.assertEqual(0, result)
        self.assertEqual(
            [
                ["sudo", "apt-get", "update"],
                ["sudo", "apt-get", "install", "-y", "docker.io"],
                ["sudo", "groupadd", "-f", "docker"],
                ["sudo", "usermod", "-aG", "docker", "testuser"],
                ["sudo", "service", "docker", "start"],
            ],
            commands,
        )

    def test_local_development_provider_prints_handoff_when_sudo_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with (
                mock.patch(
                    "scripts.gar_lib.environments.registry.codespace.local._is_wsl_or_linux",
                    return_value=True,
                ),
                mock.patch(
                    "scripts.gar_lib.environments.registry.codespace.local.shutil.which",
                    return_value="/usr/bin/apt-get",
                ),
                mock.patch.object(
                    LocalEnvironment,
                    "sudo_block_reason",
                    return_value="sudo: The no new privileges flag is set",
                ),
            ):
                with contextlib.chdir(tmp_path), contextlib.redirect_stdout(io.StringIO()) as output:
                    result = LocalEnvironment.install_dependencies(["docker"])

            self.assertEqual(1, result)
            self.assertIn("Local Docker のインストールには sudo が必要です。", output.getvalue())
            requests = list((tmp_path / ".gar" / "terminal-requests").glob("*.json"))
            self.assertEqual(1, len(requests))

    def test_github_codespaces_installs_sshfs_with_apt_get(self) -> None:
        commands: list[list[str]] = []

        def fake_run_subprocess(argv: list[str]) -> int:
            commands.append(argv)
            return 0

        with (
            mock.patch(
                "scripts.gar_lib.environments.registry.codespace.github_codespaces._is_wsl_or_linux",
                return_value=True,
            ),
            mock.patch(
                "scripts.gar_lib.environments.registry.codespace.github_codespaces.shutil.which",
                return_value="/usr/bin/apt-get",
            ),
            mock.patch.object(
                GitHubCodespacesEnvironment,
                "sudo_block_reason",
                return_value=None,
            ),
            mock.patch.object(
                GitHubCodespacesEnvironment,
                "run_subprocess",
                side_effect=fake_run_subprocess,
            ),
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                result = GitHubCodespacesEnvironment.install_dependencies(["sshfs"])

        self.assertEqual(0, result)
        self.assertEqual(
            [
                ["sudo", "apt-get", "update"],
                ["sudo", "apt-get", "install", "-y", "sshfs"],
            ],
            commands,
        )

    def test_github_codespaces_installs_gh_and_sshfs_together(self) -> None:
        commands: list[list[str]] = []

        def fake_run_subprocess(argv: list[str]) -> int:
            commands.append(argv)
            return 0

        with (
            mock.patch(
                "scripts.gar_lib.environments.registry.codespace.github_codespaces._is_wsl_or_linux",
                return_value=True,
            ),
            mock.patch(
                "scripts.gar_lib.environments.registry.codespace.github_codespaces.shutil.which",
                return_value="/usr/bin/apt-get",
            ),
            mock.patch.object(
                GitHubCodespacesEnvironment,
                "sudo_block_reason",
                return_value=None,
            ),
            mock.patch.object(
                GitHubCodespacesEnvironment,
                "run_subprocess",
                side_effect=fake_run_subprocess,
            ),
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                result = GitHubCodespacesEnvironment.install_dependencies(
                    ["gh", "sshfs"]
                )

        self.assertEqual(0, result)
        self.assertEqual(
            [
                ["sudo", "apt-get", "update"],
                ["sudo", "apt-get", "install", "-y", "gh", "sshfs"],
            ],
            commands,
        )

    def test_aws_ssm_installs_aws_cli_and_session_manager_plugin(self) -> None:
        commands: list[list[str]] = []

        def fake_run_subprocess(argv: list[str]) -> int:
            commands.append(argv)
            return 0

        with (
            mock.patch(
                "scripts.gar_lib.environments.registry.simulator.aws_ssm.platform.system",
                return_value="Linux",
            ),
            mock.patch(
                "scripts.gar_lib.environments.registry.simulator.aws_ssm.platform.machine",
                return_value="x86_64",
            ),
            mock.patch(
                "scripts.gar_lib.environments.registry.simulator.aws_ssm.shutil.which",
                return_value="/usr/bin/tool",
            ),
            mock.patch.object(
                AwsSsmEnvironment,
                "sudo_block_reason",
                return_value=None,
            ),
            mock.patch.object(
                AwsSsmEnvironment,
                "run_subprocess",
                side_effect=fake_run_subprocess,
            ),
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                result = AwsSsmEnvironment.install_dependencies(
                    ["aws", "session-manager-plugin"]
                )

        self.assertEqual(0, result)
        self.assertIn(
            [
                "curl",
                "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip",
                "-o",
                mock.ANY,
            ],
            commands,
        )
        self.assertIn(["unzip", "-q", mock.ANY, "-d", mock.ANY], commands)
        self.assertTrue(
            any(
                command[0] == "sudo"
                and Path(command[-1]).as_posix().endswith("/aws/install")
                for command in commands
            )
        )
        self.assertIn(
            [
                "curl",
                "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/"
                "ubuntu_64bit/session-manager-plugin.deb",
                "-o",
                mock.ANY,
            ],
            commands,
        )
        self.assertIn(["sudo", "dpkg", "-i", mock.ANY], commands)

    def test_aws_ssm_runtime_operations_fail_closed(self) -> None:
        with mock.patch("scripts.gar_lib.environments.registry.simulator.aws_ssm.subprocess.run") as run:
            result = AwsSsmEnvironment.run_remote(
                "vibecode-graviton",
                "echo hello",
                capture_output=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertIn("deprecated", result.stderr)
        run.assert_not_called()

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(1, AwsSsmEnvironment.push_file("target", "src", "dest"))
            self.assertEqual(1, AwsSsmEnvironment.pull_file("target", "src", "dest"))
            self.assertEqual(1, AwsSsmEnvironment.start_port_forward("target"))
            self.assertEqual(1, AwsSsmEnvironment.stop_port_forward("target"))
            self.assertEqual(1, AwsSsmEnvironment.status_port_forward("target"))

        self.assertIn("ssh_remote", stderr.getvalue())
        self.assertIn("exit 1", AwsSsmEnvironment.interactive_shell_script("target"))

    def test_adb_usb_installs_adb_with_apt_get(self) -> None:
        commands: list[list[str]] = []

        def fake_run_subprocess(argv: list[str]) -> int:
            commands.append(argv)
            return 0

        with (
            mock.patch(
                "scripts.gar_lib.environments.registry.target.adb_usb.platform.system",
                return_value="Linux",
            ),
            mock.patch(
                "scripts.gar_lib.environments.registry.target.adb_usb.shutil.which",
                return_value="/usr/bin/apt-get",
            ),
            mock.patch.object(
                AdbUsbEnvironment,
                "sudo_block_reason",
                return_value=None,
            ),
            mock.patch.object(
                AdbUsbEnvironment,
                "run_subprocess",
                side_effect=fake_run_subprocess,
            ),
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                result = AdbUsbEnvironment.install_dependencies(["adb"])

        self.assertEqual(0, result)
        self.assertEqual(
            [
                ["sudo", "apt-get", "update"],
                ["sudo", "apt-get", "install", "-y", "adb"],
            ],
            commands,
        )

    def test_github_codespaces_prints_handoff_when_sudo_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with (
                mock.patch(
                    "scripts.gar_lib.environments.registry.codespace.github_codespaces._is_wsl_or_linux",
                    return_value=True,
                ),
                mock.patch(
                    "scripts.gar_lib.environments.registry.codespace.github_codespaces.shutil.which",
                    return_value="/usr/bin/apt-get",
                ),
                mock.patch.object(
                    GitHubCodespacesEnvironment,
                    "sudo_block_reason",
                    return_value="sudo: The no new privileges flag is set",
                ),
                mock.patch("scripts.gar_lib.environments.base.Path.cwd", return_value=tmp_path),
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = GitHubCodespacesEnvironment.install_dependencies(["gh"])

            self.assertEqual(1, result)
            text = output.getvalue()
            self.assertIn("ユーザーの通常ターミナルで次のコマンドを実行してください", text)
            self.assertIn("sudo apt-get install -y gh", text)
            self.assertIn("VSCode integrated terminal にも実行要求を作成しました", text)

            requests = list((tmp_path / ".gar" / "terminal-requests").glob("*.json"))
            self.assertEqual(1, len(requests))
            request = json.loads(requests[0].read_text(encoding="utf-8"))
            self.assertEqual("Gapless Agent Runtime User Action", request["title"])
            self.assertIn("sudo apt-get install -y gh", request["command"])


if __name__ == "__main__":
    unittest.main()
