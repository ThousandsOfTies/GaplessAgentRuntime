from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts.gar_lib.access.channel import AccessResult
from scripts.gar_lib.api import Target
from scripts.gar_lib.core.artifact import ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.target.file_transfer import FileTransferTargetEnvironment, TargetConfigurationReport
from scripts.gar_lib.target.lifecycle import TargetApplication, TargetDiagnosticReport, TargetLifecycleResult


class GarTargetSystemEnvironmentTest(unittest.TestCase):
    def _environment(self, *, uid: str = "1000\n") -> tuple[FileTransferTargetEnvironment, mock.Mock, mock.Mock]:
        commands = mock.Mock(host="target")
        commands.run.side_effect = lambda command: subprocess.CompletedProcess(
            [], 0, uid if command == "id -u" else "", ""
        )
        files = mock.Mock()
        files.push.return_value = AccessResult(("channel",), 0)
        return (
            FileTransferTargetEnvironment(commands, files, privileged_install=True, prepare_recipe=Path("/recipe")),
            commands,
            files,
        )

    def test_system_env_uses_separate_destination_and_sudo_installer(self) -> None:
        environment, commands, files = self._environment()

        report = environment.configure_system_env("stream-rx", {"BETA": "two", "ALPHA": "one"})

        self.assertEqual("/etc/gar/system/stream-rx.env", report.destination)
        self.assertTrue(report.sha256)
        self.assertEqual(1, files.push.call_count)
        installed = [call.args[0] for call in commands.run.call_args_list]
        self.assertTrue(
            any(command.startswith("sudo -n /usr/local/lib/gar/gar-target-install install") for command in installed)
        )
        self.assertTrue(any("/etc/gar/system/stream-rx.env" in command and " 0644" in command for command in installed))

    def test_system_env_uses_direct_installer_for_root(self) -> None:
        environment, commands, _ = self._environment(uid="0\n")

        environment.configure_system_env("stream-rx", {"PORT": "5600"})

        installed = [call.args[0] for call in commands.run.call_args_list]
        self.assertTrue(
            any(command.startswith("/usr/local/lib/gar/gar-target-install install") for command in installed)
        )
        self.assertFalse(any(command.startswith("sudo -n ") for command in installed))

    def test_system_env_rejects_unsafe_values_before_transfer(self) -> None:
        environment, commands, files = self._environment()

        for app, values in (("../bad", {"SAFE": "x"}), ("demo", {"bad-name": "x"}), ("demo", {"SAFE": "x\ny"})):
            with self.subTest(app=app, values=values):
                with self.assertRaises(GarDomainError):
                    environment.configure_system_env(app, values)

        files.push.assert_not_called()
        commands.run.assert_not_called()

    def test_target_api_requires_recipe_backed_environment(self) -> None:
        workspace = Workspace("ws", "Local/Product", "Product", {"type": "local", "path": "/tmp/product"})
        target = Target(workspace, mock.Mock())
        with mock.patch("scripts.gar_lib.api.target_environment_for", return_value=mock.Mock()):
            with self.assertRaisesRegex(GarDomainError, "recipe-backed"):
                target.configure_system_env(app="demo", values={"PORT": "5600"})

    def test_target_start_converges_latest_artifact_with_recipe_lifecycle(self) -> None:
        workspace = Workspace("ws", "Local/Product", "Product", {"type": "local", "path": "/tmp/product"})
        artifacts = mock.Mock()
        artifacts.latest.return_value.bundle_path = Path("/tmp/artifact")
        target = Target(workspace, artifacts)
        application = TargetApplication("demo", expected_build_id="build-1")
        success = TargetLifecycleResult("status", "demo", 0)
        diagnostic = TargetDiagnosticReport(
            application, success, success, TargetLifecycleResult("build", "demo", 0, "build-1\n")
        )
        lifecycle = mock.Mock()
        lifecycle.reload.return_value = TargetLifecycleResult("reload", "demo", 0)
        lifecycle.diag.return_value = diagnostic

        with (
            mock.patch("scripts.gar_lib.api.target_environment_for", return_value=mock.Mock()),
            mock.patch("scripts.gar_lib.api.target_application_from_artifact", return_value=application),
            mock.patch("scripts.gar_lib.api.target_lifecycle_for", return_value=lifecycle),
        ):
            report = target.start(app="demo")

        self.assertTrue(report.ok)
        lifecycle.reload.assert_called_once_with(application)
        lifecycle.diag.assert_called_once_with(application)

    def test_target_start_validates_before_installing_system_env(self) -> None:
        workspace = Workspace("ws", "Local/Product", "Product", {"type": "local", "path": "/tmp/product"})
        artifacts = mock.Mock()
        artifacts.latest.return_value.bundle_path = Path("/tmp/artifact")
        target = Target(workspace, artifacts)
        environment = mock.create_autospec(FileTransferTargetEnvironment, instance=True)
        environment.validate_deployment.side_effect = GarDomainError("installed recipe mismatch")

        with (
            mock.patch("scripts.gar_lib.api.target_environment_for", return_value=environment),
            mock.patch("scripts.gar_lib.api.target_lifecycle_for", return_value=mock.Mock()),
        ):
            with self.assertRaisesRegex(GarDomainError, "recipe mismatch"):
                target.start(app="demo", system_env={"PORT": "5600"})

        environment.configure_system_env.assert_not_called()

    def test_target_start_validates_then_installs_env_before_reload(self) -> None:
        workspace = Workspace("ws", "Local/Product", "Product", {"type": "local", "path": "/tmp/product"})
        artifacts = mock.Mock()
        artifact = mock.Mock(kind=ArtifactKind.TARGET_APP, bundle_path=Path("/tmp/artifact"))
        artifacts.latest.return_value = artifact
        target = Target(workspace, artifacts)
        application = TargetApplication("demo", expected_build_id="build-1")
        events: list[str] = []
        environment = mock.create_autospec(FileTransferTargetEnvironment, instance=True)
        environment.validate_deployment.side_effect = lambda _: events.append("validate")
        environment.configure_system_env.side_effect = lambda *_: events.append("configure")
        lifecycle = mock.Mock()
        lifecycle.reload.side_effect = lambda _: events.append("reload") or TargetLifecycleResult("reload", "demo", 0)
        success = TargetLifecycleResult("status", "demo", 0)
        lifecycle.diag.return_value = TargetDiagnosticReport(
            application, success, success, TargetLifecycleResult("build", "demo", 0, "build-1\n")
        )

        with (
            mock.patch("scripts.gar_lib.api.target_environment_for", return_value=environment),
            mock.patch("scripts.gar_lib.api.target_application_from_artifact", return_value=application),
            mock.patch("scripts.gar_lib.api.target_lifecycle_for", return_value=lifecycle),
        ):
            report = target.start(app="demo", system_env={"PORT": "5600"})

        self.assertTrue(report.ok)
        self.assertEqual(["validate", "configure", "reload"], events)
        environment.configure_system_env.assert_called_once_with("demo", {"PORT": "5600"})

    def test_deploy_validates_then_installs_env_before_placement_and_reload(self) -> None:
        workspace = Workspace("ws", "Local/Product", "Product", {"type": "local", "path": "/tmp/product"})
        artifacts = mock.Mock()
        artifact = mock.Mock(kind=ArtifactKind.TARGET_APP, bundle_path=Path("/tmp/artifact"))
        artifacts.latest.return_value = artifact
        target = Target(workspace, artifacts)
        application = TargetApplication("demo", expected_build_id="build-1")
        events: list[str] = []
        environment = mock.create_autospec(FileTransferTargetEnvironment, instance=True)
        environment.validate_deployment.side_effect = lambda _: events.append("validate")
        environment.configure_system_env.side_effect = lambda *_: (
            events.append("configure")
            or TargetConfigurationReport("demo", Path("<system:demo>"), "/etc/gar/system/demo.env", "sha")
        )
        environment.deploy.side_effect = lambda _: events.append("deploy")
        lifecycle = mock.Mock()
        lifecycle.reload.side_effect = lambda _: events.append("reload") or TargetLifecycleResult("reload", "demo", 0)
        success = TargetLifecycleResult("status", "demo", 0)
        lifecycle.diag.return_value = TargetDiagnosticReport(
            application, success, success, TargetLifecycleResult("build", "demo", 0, "build-1\n")
        )

        with (
            mock.patch("scripts.gar_lib.api.target_environment_for", return_value=environment),
            mock.patch("scripts.gar_lib.api.target_application_from_artifact", return_value=application),
            mock.patch("scripts.gar_lib.api.target_lifecycle_for", return_value=lifecycle),
        ):
            result = target.deploy_report(system_env_app="demo", system_env={"PORT": "5600"})

        self.assertTrue(result.report.ok)
        self.assertEqual("/etc/gar/system/demo.env", result.configuration.destination)
        self.assertEqual(["validate", "configure", "deploy", "reload"], events)

    def test_deploy_validates_artifact_before_installing_system_env(self) -> None:
        workspace = Workspace("ws", "Local/Product", "Product", {"type": "local", "path": "/tmp/product"})
        artifacts = mock.Mock()
        artifact = mock.Mock(kind=ArtifactKind.TARGET_APP, bundle_path=Path("/tmp/artifact"))
        artifacts.latest.return_value = artifact
        target = Target(workspace, artifacts)
        environment = mock.create_autospec(FileTransferTargetEnvironment, instance=True)
        environment.validate_deployment.side_effect = GarDomainError("wrong target")

        with (
            mock.patch("scripts.gar_lib.api.target_environment_for", return_value=environment),
            mock.patch("scripts.gar_lib.api.target_lifecycle_for", return_value=mock.Mock()),
        ):
            with self.assertRaisesRegex(GarDomainError, "wrong target"):
                target.deploy_report(system_env_app="demo", system_env={"PORT": "5600"})

        environment.configure_system_env.assert_not_called()
        environment.deploy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
