from __future__ import annotations

import contextlib
import io
import json
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from scripts.agp_lib.environments.base import DevEnvironment
from scripts.agp_lib.environments.discovery import discover_environment_providers
from scripts.agp_lib.environments.registry.device.adb_usb import AdbUsbEnvironment
from scripts.agp_lib.environments.registry.development.github_codespaces import (
    GitHubCodespacesEnvironment,
)
from scripts.agp_lib.environments.registry.simulation.aws_ssm import AwsSsmEnvironment


class AgpDiscoveryTest(unittest.TestCase):
    def test_discovers_registry_providers(self) -> None:
        providers = discover_environment_providers()
        provider_ids = {provider.provider_id for provider in providers}

        self.assertIn("github_codespaces", provider_ids)
        self.assertIn("aws_ssm", provider_ids)
        self.assertIn("ssh_remote", provider_ids)
        self.assertIn("local", provider_ids)
        self.assertIn("adb_usb", provider_ids)
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
            "development",
            categories_by_provider["github_codespaces"],
        )
        self.assertEqual("simulation", categories_by_provider["aws_ssm"])
        self.assertEqual("device", categories_by_provider["adb_usb"])

    def test_provider_ids_are_unique(self) -> None:
        providers = discover_environment_providers()
        provider_ids = [provider.provider_id for provider in providers]

        self.assertEqual(len(provider_ids), len(set(provider_ids)))

    def test_github_codespaces_installs_gh_with_apt_get(self) -> None:
        commands: list[list[str]] = []

        def fake_run_subprocess(argv: list[str]) -> int:
            commands.append(argv)
            return 0

        with (
            mock.patch(
                "scripts.agp_lib.environments.registry.development.github_codespaces._is_wsl_or_linux",
                return_value=True,
            ),
            mock.patch(
                "scripts.agp_lib.environments.registry.development.github_codespaces.shutil.which",
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

    def test_github_codespaces_installs_sshfs_with_apt_get(self) -> None:
        commands: list[list[str]] = []

        def fake_run_subprocess(argv: list[str]) -> int:
            commands.append(argv)
            return 0

        with (
            mock.patch(
                "scripts.agp_lib.environments.registry.development.github_codespaces._is_wsl_or_linux",
                return_value=True,
            ),
            mock.patch(
                "scripts.agp_lib.environments.registry.development.github_codespaces.shutil.which",
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
                "scripts.agp_lib.environments.registry.development.github_codespaces._is_wsl_or_linux",
                return_value=True,
            ),
            mock.patch(
                "scripts.agp_lib.environments.registry.development.github_codespaces.shutil.which",
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
                "scripts.agp_lib.environments.registry.simulation.aws_ssm.platform.system",
                return_value="Linux",
            ),
            mock.patch(
                "scripts.agp_lib.environments.registry.simulation.aws_ssm.platform.machine",
                return_value="x86_64",
            ),
            mock.patch(
                "scripts.agp_lib.environments.registry.simulation.aws_ssm.shutil.which",
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
                command[0] == "sudo" and command[-1].endswith("/aws/install")
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

    def test_adb_usb_installs_adb_with_apt_get(self) -> None:
        commands: list[list[str]] = []

        def fake_run_subprocess(argv: list[str]) -> int:
            commands.append(argv)
            return 0

        with (
            mock.patch(
                "scripts.agp_lib.environments.registry.device.adb_usb.platform.system",
                return_value="Linux",
            ),
            mock.patch(
                "scripts.agp_lib.environments.registry.device.adb_usb.shutil.which",
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
                    "scripts.agp_lib.environments.registry.development.github_codespaces._is_wsl_or_linux",
                    return_value=True,
                ),
                mock.patch(
                    "scripts.agp_lib.environments.registry.development.github_codespaces.shutil.which",
                    return_value="/usr/bin/apt-get",
                ),
                mock.patch.object(
                    GitHubCodespacesEnvironment,
                    "sudo_block_reason",
                    return_value="sudo: The no new privileges flag is set",
                ),
                mock.patch("scripts.agp_lib.environments.base.Path.cwd", return_value=tmp_path),
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = GitHubCodespacesEnvironment.install_dependencies(["gh"])

            self.assertEqual(1, result)
            text = output.getvalue()
            self.assertIn("ユーザーの通常ターミナルで次のコマンドを実行してください", text)
            self.assertIn("sudo apt-get install -y gh", text)
            self.assertIn("VSCode integrated terminal にも実行要求を作成しました", text)

            requests = list((tmp_path / ".agp" / "terminal-requests").glob("*.json"))
            self.assertEqual(1, len(requests))
            request = json.loads(requests[0].read_text(encoding="utf-8"))
            self.assertEqual("AgentCockpit User Action", request["title"])
            self.assertIn("sudo apt-get install -y gh", request["command"])


if __name__ == "__main__":
    unittest.main()
