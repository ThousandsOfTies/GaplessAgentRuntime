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

from scripts.gar_lib.access.channel import AccessResult
from scripts.gar_lib.api import Gar
from scripts.gar_lib.artifacts.provenance import TargetToolsProvenance
from scripts.gar_lib.cli import main
from scripts.gar_lib.commands.recovery import plan_access_recovery
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.errors import AccessConnectionError, GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.target.composition import target_environment_for
from scripts.gar_lib.target.environment import TargetPlacementError
from scripts.gar_lib.target.file_transfer import FileTransferTargetEnvironment
from scripts.gar_lib.target.lifecycle import (
    CommandTargetLifecycle,
    TargetApplication,
    TargetDeploymentConvergenceError,
    TargetDeploymentReport,
    TargetDiagnosticReport,
    TargetLifecycleResult,
)
from scripts.gar_lib.target.manifest import (
    TARGET_LIFECYCLE_CONTRACT,
    TargetManifest,
    TargetManifestValidationError,
    discover_target_manifests,
)
from scripts.gar_lib.target.ssh_prepare import prepare_ssh_target


def access_result(returncode: int = 0, stdout: str = "", stderr: str = "") -> AccessResult:
    return AccessResult((), returncode, stdout, stderr)


def convergence_with_access_failure(report: TargetDeploymentReport) -> TargetDeploymentConvergenceError:
    access_error = AccessConnectionError(
        channel="ssh",
        endpoint="target",
        reason="target_prepare_required",
        returncode=1,
    )
    placement_error = TargetPlacementError(
        str(access_error),
        placed_destinations=report.placed_destinations or ("/opt/gar/apps/demo",),
        placement_complete=not report.partial,
    )
    placement_error.__cause__ = access_error
    convergence = TargetDeploymentConvergenceError(report)
    convergence.__cause__ = placement_error
    return convergence


class TargetLifecycleManifestTests(unittest.TestCase):
    def test_manifest_exposes_lifecycle_v1_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_dir = Path(tmp) / "linux"
            recipe = target_dir / "provisioning" / "linux"
            recipe.mkdir(parents=True)
            (target_dir / "target.json").write_text(
                json.dumps(
                    {
                        "id": "linux",
                        "displayName": "Linux",
                        "description": "test",
                        "toolsRoot": "targets/linux",
                        "defaultBackends": {"target": "ssh_scp"},
                        "provisioning": {
                            "ssh_scp": {
                                "type": "ssh-script",
                                "path": "provisioning/linux",
                                "recipeVersion": 2,
                                "lifecycle": {
                                    "type": TARGET_LIFECYCLE_CONTRACT,
                                    "command": "/usr/local/lib/gar/gar-target-lifecycle",
                                },
                            }
                        },
                        "compatibility": {
                            "architecture": "aarch64",
                            "abi": "gnu",
                            "libc": "glibc",
                            "toolchainTriple": "aarch64-linux-gnu",
                        },
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {"GAR_TOOLS_TARGETS": tmp}):
                manifest = discover_target_manifests()[0]

        capability = manifest.lifecycle_capability("ssh_scp")
        self.assertIsNotNone(capability)
        assert capability is not None
        self.assertEqual(TARGET_LIFECYCLE_CONTRACT, capability.type)
        self.assertEqual("/usr/local/lib/gar/gar-target-lifecycle", capability.command)
        self.assertEqual(2, manifest.recipe_version("ssh_scp"))
        self.assertEqual("aarch64", manifest.compatibility["architecture"])
        self.assertEqual("aarch64-linux-gnu", manifest.compatibility["toolchainTriple"])

    def test_manifest_rejects_unknown_or_relative_lifecycle_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_dir = Path(tmp) / "linux"
            (target_dir / "provisioning" / "linux").mkdir(parents=True)
            (target_dir / "target.json").write_text(
                json.dumps(
                    {
                        "id": "linux",
                        "displayName": "Linux",
                        "description": "test",
                        "toolsRoot": "targets/linux",
                        "defaultBackends": {"target": "ssh_scp"},
                        "provisioning": {
                            "ssh_scp": {
                                "type": "ssh-script",
                                "path": "provisioning/linux",
                                "lifecycle": {
                                    "type": "product-systemd-v1",
                                    "command": "bin/manage-app",
                                },
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.dict(os.environ, {"GAR_TOOLS_TARGETS": tmp}),
                self.assertRaises(TargetManifestValidationError) as caught,
            ):
                discover_target_manifests()

        fields = {issue.field for issue in caught.exception.issues}
        self.assertIn("provisioning.ssh_scp.lifecycle.type", fields)

    def test_manifest_rejects_unknown_or_empty_compatibility_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_dir = Path(tmp) / "linux"
            target_dir.mkdir()
            (target_dir / "target.json").write_text(
                json.dumps(
                    {
                        "id": "linux",
                        "displayName": "Linux",
                        "description": "test",
                        "toolsRoot": "targets/linux",
                        "defaultBackends": {"target": "ssh_scp"},
                        "compatibility": {"architecture": "", "wordSize": "64"},
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.dict(os.environ, {"GAR_TOOLS_TARGETS": tmp}),
                self.assertRaises(TargetManifestValidationError) as caught,
            ):
                discover_target_manifests()

        fields = {issue.field for issue in caught.exception.issues}
        self.assertIn("compatibility.architecture", fields)
        self.assertIn("compatibility.wordSize", fields)

    def test_lifecycle_target_registers_before_reload_instead_of_starting_during_transfer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_dir = Path(tmp) / "targets" / "linux"
            recipe = target_dir / "provisioning" / "linux"
            recipe.mkdir(parents=True)
            manifest_path = target_dir / "target.json"
            manifest_path.write_text("{}\n", encoding="utf-8")
            manifest = TargetManifest(
                id="linux",
                display_name="Linux",
                description="test",
                tools_root="targets/linux",
                default_backends={"target": "ssh_scp"},
                backend_notes={},
                provisioning={
                    "ssh_scp": {
                        "type": "ssh-script",
                        "path": "provisioning/linux",
                        "recipeVersion": 1,
                        "lifecycle": {
                            "type": TARGET_LIFECYCLE_CONTRACT,
                            "command": "/usr/local/lib/gar/gar-target-lifecycle",
                        },
                    }
                },
                source_path=manifest_path,
            )
            selected_workspace = Workspace(
                id="ws",
                name="Local/Product",
                branch="Product",
                connection={"type": "local", "path": "/tmp/product"},
                selected_target="linux",
                selected_environments={"target": "ssh_scp"},
                target={"host": "target"},
            )

            with mock.patch(
                "scripts.gar_lib.target.composition.discover_target_manifests",
                return_value=[manifest],
            ):
                environment = target_environment_for(selected_workspace)

        self.assertEqual("register-app", environment.app_install_action)
        self.assertTrue(environment.prepare_lifecycle)


class CommandTargetLifecycleTests(unittest.TestCase):
    def test_non_root_target_uses_constrained_sudo_lifecycle_command(self) -> None:
        channel = mock.Mock(host="raspi5")
        channel.run.side_effect = [
            access_result(stdout="1000\n"),
            access_result(stdout="running\n"),
            access_result(stdout="healthy\n"),
            access_result(stdout="build-123\n"),
        ]
        lifecycle = CommandTargetLifecycle(channel, "/usr/local/lib/gar/gar-target-lifecycle")
        application = TargetApplication("demo", expected_build_id="build-123")

        report = lifecycle.diag(application)

        self.assertTrue(report.ok)
        self.assertEqual("build-123", report.running_build_id)
        commands = [item.args[0] for item in channel.run.call_args_list]
        self.assertEqual("id -u", commands[0])
        self.assertTrue(all(command.startswith("sudo -n ") for command in commands[1:]))
        self.assertIn(" status demo", commands[1])
        self.assertIn(" health demo", commands[2])
        self.assertIn(" running-build-id demo", commands[3])

    def test_root_target_reload_passes_expected_build_id_without_sudo(self) -> None:
        channel = mock.Mock(host="luckfox-lyra")
        channel.run.side_effect = [access_result(stdout="0\n"), access_result(stdout="reloaded\n")]
        lifecycle = CommandTargetLifecycle(channel, "/usr/local/lib/gar/gar-target-lifecycle")

        result = lifecycle.reload(TargetApplication("demo", expected_build_id="build-123"))

        self.assertTrue(result.ok)
        command = channel.run.call_args_list[1].args[0]
        self.assertEqual(
            "/usr/local/lib/gar/gar-target-lifecycle reload demo --build-id build-123",
            command,
        )

    def test_sudo_auth_failure_requests_target_prepare_handoff(self) -> None:
        channel = mock.Mock(host="raspi5")
        channel.run.side_effect = [
            access_result(stdout="1000\n"),
            access_result(1, stderr="sudo: a password is required\n"),
        ]
        lifecycle = CommandTargetLifecycle(channel, "/usr/local/lib/gar/gar-target-lifecycle")

        with self.assertRaises(AccessConnectionError) as caught:
            lifecycle.status(TargetApplication("demo"))

        self.assertEqual("target_prepare_required", caught.exception.reason)
        selected_workspace = Workspace(
            id="ws",
            name="Local/Product",
            branch="Product",
            connection={"type": "local", "path": "/tmp/product"},
        )
        recovery = plan_access_recovery(
            caught.exception,
            workspace=selected_workspace,
            retry_command="gar target status --app demo",
            purpose="target",
        )
        self.assertEqual(
            ("gar", "target", "prepare", "--workspace", "Local/Product"),
            recovery.terminal_command,
        )

    def test_installer_sudo_auth_failure_uses_the_same_prepare_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "files" / "demo"
            source.mkdir(parents=True)
            (source / "run").write_text("#!/bin/sh\n", encoding="utf-8")
            (root / "artifact.json").write_text(
                json.dumps({"deploy": {"app": {"files": [{"src": "files/demo", "dest": "/opt/gar/apps/demo"}]}}}),
                encoding="utf-8",
            )
            artifact = Artifact(ArtifactKind.TARGET_APP, mock.Mock(), root)
            channel = mock.Mock(host="raspi5")

            def run(command: str) -> AccessResult:
                if command == "id -u":
                    return access_result(stdout="1000\n")
                if "gar-target-install install" in command:
                    return access_result(1, stderr="sudo: a password is required\n")
                return access_result()

            channel.run.side_effect = run
            file_channel = mock.Mock()
            file_channel.push.return_value = access_result()
            environment = FileTransferTargetEnvironment(
                channel,
                file_channel,
                privileged_install=True,
            )

            with self.assertRaises(AccessConnectionError) as caught:
                environment.deploy(artifact)

        self.assertEqual("target_prepare_required", caught.exception.reason)

    def test_normal_deploy_ignores_persistent_configuration_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            app = root / "files" / "demo"
            app.mkdir(parents=True)
            (app / "run").write_text("#!/bin/sh\n", encoding="utf-8")
            environment_file = root / "files" / "demo.env"
            environment_file.write_text("PORT=5000\n", encoding="utf-8")
            (root / "artifact.json").write_text(
                json.dumps(
                    {
                        "deploy": {
                            "app": {
                                "files": [
                                    {"src": "files/demo", "dest": "/opt/gar/apps/demo"},
                                    {"src": "files/demo.env", "dest": "/etc/gar/demo.env"},
                                ]
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            artifact = Artifact(ArtifactKind.TARGET_APP, mock.Mock(), root)
            environment = FileTransferTargetEnvironment(
                mock.Mock(),
                mock.Mock(),
                app_install_action=None,
            )

            with mock.patch.object(environment, "_install_source") as install:
                environment.deploy(artifact)

        install.assert_called_once_with(app, "/opt/gar/apps/demo", None)

    def test_file_transfer_reports_destinations_placed_before_a_later_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "files" / "demo"
            app.mkdir(parents=True)
            (app / "run").write_text("#!/bin/sh\n", encoding="utf-8")
            settings_file = root / "files" / "demo.conf"
            settings_file.write_text("PORT=5000\n", encoding="utf-8")
            (root / "artifact.json").write_text(
                json.dumps(
                    {
                        "deploy": {
                            "app": {
                                "files": [
                                    {"src": "files/demo", "dest": "/opt/gar/apps/demo"},
                                    {"src": "files/demo.conf", "dest": "/etc/gar/demo.conf"},
                                ]
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            artifact = Artifact(ArtifactKind.TARGET_APP, mock.Mock(), root)
            environment = FileTransferTargetEnvironment(
                mock.Mock(),
                mock.Mock(),
                app_install_action=None,
            )

            with (
                mock.patch.object(
                    environment,
                    "_install_source",
                    side_effect=(None, GarDomainError("settings install failed")),
                ),
                self.assertRaises(TargetPlacementError) as caught,
            ):
                environment.deploy(artifact)

        self.assertTrue(caught.exception.partial)
        self.assertEqual(("/opt/gar/apps/demo",), caught.exception.placed_destinations)

    def test_deployment_failure_payload_explicitly_reports_placed_not_running(self) -> None:
        application = TargetApplication("demo", expected_build_id="build-new")
        channel = mock.Mock(host="target")
        channel.run.side_effect = [
            access_result(stdout="0\n"),
            access_result(1, stderr="not active\n"),
            access_result(1, stderr="unhealthy\n"),
            access_result(1, stderr="no running build\n"),
        ]
        diagnostic = CommandTargetLifecycle(
            channel,
            "/usr/local/lib/gar/gar-target-lifecycle",
        ).diag(application)
        report = TargetDeploymentReport(
            application=application,
            artifact_path="/tmp/artifact",
            placed=True,
            diagnostic=diagnostic,
            verification="lifecycle-v1",
        )

        payload = report.to_payload(workspace="Local/Product", target_id="linux")

        self.assertFalse(report.ok)
        self.assertTrue(payload["placed"])
        self.assertFalse(payload["running"])
        self.assertEqual({"available": False, "attempted": False}, payload["rollback"])

    def test_reload_failure_keeps_deployment_report_nonzero_even_if_old_status_looks_healthy(self) -> None:
        application = TargetApplication("demo", expected_build_id="build-123")
        diagnostic = TargetDiagnosticReport(
            application=application,
            status=TargetLifecycleResult("status", "demo", 0, "running\n", ""),
            health=TargetLifecycleResult("health", "demo", 0, "healthy\n", ""),
            build_id=TargetLifecycleResult("running-build-id", "demo", 0, "build-123\n", ""),
        )
        report = TargetDeploymentReport(
            application=application,
            artifact_path="/tmp/artifact",
            placed=True,
            reload=TargetLifecycleResult("reload", "demo", 1, "", "restart failed\n"),
            diagnostic=diagnostic,
            verification="lifecycle-v1",
        )

        self.assertFalse(report.ok)
        self.assertFalse(report.running)
        self.assertEqual(1, report.exit_code)


class TargetLifecyclePrepareTests(unittest.TestCase):
    def test_environment_prepare_passes_active_recipe_identity(self) -> None:
        channel = mock.Mock(host="raspi5", config_path=Path("/tmp/ssh-config"))
        provenance = TargetToolsProvenance(
            target_id="raspberry-pi-5",
            gar_tools_commit="c" * 40,
            target_recipe_version="2",
        )
        environment = FileTransferTargetEnvironment(
            channel,
            mock.Mock(),
            privileged_install=True,
            prepare_recipe=Path("/tmp/recipe"),
            prepare_lifecycle=True,
            active_tools_provenance=provenance,
        )

        with mock.patch("scripts.gar_lib.target.file_transfer.prepare_ssh_target") as prepare:
            environment.prepare()

        prepare.assert_called_once_with(
            "raspi5",
            Path("/tmp/recipe"),
            target_id="raspberry-pi-5",
            recipe_version="2",
            gar_tools_commit="c" * 40,
            config_path=Path("/tmp/ssh-config"),
            include_lifecycle=True,
        )

    def test_prepare_stages_target_owned_lifecycle_helper_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            recipe = Path(tmp)
            for name in ("prepare.sh", "gar-target-install", "gar-app@.service", "gar-target-lifecycle"):
                (recipe / name).write_text("#!/bin/sh\n", encoding="utf-8")

            def completed(argv: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                stdout = "user\n" if argv[-1] == "id -un" else ""
                return subprocess.CompletedProcess(argv, 0, stdout, "")

            with mock.patch("scripts.gar_lib.target.ssh_prepare.subprocess.run", side_effect=completed) as run:
                prepare_ssh_target(
                    "raspi5",
                    recipe,
                    target_id="linux",
                    recipe_version="2",
                    gar_tools_commit="c" * 40,
                    config_path=Path("/tmp/ssh-config"),
                    include_lifecycle=True,
                )

        scp_command = run.call_args_list[2].args[0]
        self.assertIn(str(recipe / "gar-target-lifecycle"), scp_command)
        self.assertTrue(any(Path(argument).name == "recipe-version" for argument in scp_command))
        bootstrap = run.call_args_list[3].args[0]
        self.assertIn("/gar-target-lifecycle", bootstrap[-1])
        self.assertTrue(bootstrap[-1].endswith("/recipe-version"))


class TargetLifecycleCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Workspace(
            id="ws",
            name="Local/Product",
            branch="Product",
            connection={"type": "local", "path": "/tmp/product"},
            selected_target="linux",
            selected_environments={"target": "ssh_scp"},
            target={"host": "target"},
        )

    def test_status_log_and_diag_json_are_machine_readable(self) -> None:
        target_api = mock.Mock()
        target_api.status.return_value = TargetLifecycleResult("status", "demo", 0, "running\n", "")
        target_api.log.return_value = TargetLifecycleResult("log", "demo", 0, "line one\n", "")
        application = TargetApplication("demo", expected_build_id="build-123")
        target_api.diag.return_value = TargetDiagnosticReport(
            application=application,
            status=TargetLifecycleResult("status", "demo", 0, "running\n", ""),
            health=TargetLifecycleResult("health", "demo", 0, "healthy\n", ""),
            build_id=TargetLifecycleResult("running-build-id", "demo", 0, "build-123\n", ""),
        )
        gar = mock.Mock(target=target_api)

        for argv in (
            ["target", "status", "--json", "--workspace", "Local/Product"],
            ["target", "log", "--json", "--lines", "25", "--workspace", "Local/Product"],
            ["target", "diag", "--json", "--workspace", "Local/Product"],
        ):
            output = io.StringIO()
            with (
                mock.patch("scripts.gar_lib.commands.target.resolve_workspace", return_value=self.workspace),
                mock.patch("scripts.gar_lib.commands.target.Gar", return_value=gar),
                contextlib.redirect_stdout(output),
            ):
                exit_code = main(argv)

            self.assertEqual(0, exit_code)
            payload = json.loads(output.getvalue())
            self.assertEqual("Local/Product", payload["workspace"])
            self.assertEqual("linux", payload["target_id"])
            self.assertTrue(payload["ok"])

        target_api.log.assert_called_once_with(app=None, lines=25)

    def test_json_actions_report_workspace_resolution_failure_on_stdout(self) -> None:
        for action in ("deploy", "status", "log", "diag"):
            for selector in ("Missing/Product", None):
                with self.subTest(action=action, selector=selector):
                    output = io.StringIO()
                    errors = io.StringIO()
                    argv = ["target", action, "--json"]
                    if selector is not None:
                        argv.extend(("--workspace", selector))
                    with (
                        mock.patch(
                            "scripts.gar_lib.commands.target.resolve_workspace",
                            side_effect=GarDomainError("workspace could not be resolved"),
                        ),
                        contextlib.redirect_stdout(output),
                        contextlib.redirect_stderr(errors),
                    ):
                        exit_code = main(argv)

                    payload = json.loads(output.getvalue())
                    self.assertEqual(1, exit_code)
                    self.assertEqual(f"target.{action}", payload["command"])
                    self.assertEqual(selector, payload["workspace"])
                    self.assertIsNone(payload["target_id"])
                    self.assertFalse(payload["ok"])
                    self.assertEqual("workspace could not be resolved", payload["error"])
                    self.assertEqual("", errors.getvalue())

    def test_json_actions_capture_malformed_latest_manifest_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            kind_root = project_root / ".gar" / "artifacts" / self.workspace.id / ArtifactKind.TARGET_APP.value
            snapshot = kind_root / "bad-build"
            snapshot.mkdir(parents=True)
            (snapshot / "artifact.json").write_text("{not-json\n", encoding="utf-8")
            (kind_root / "latest.json").write_text(
                json.dumps({"build_id": snapshot.name}),
                encoding="utf-8",
            )

            for action in ("deploy", "status", "log", "diag"):
                with self.subTest(action=action):
                    output = io.StringIO()
                    errors = io.StringIO()
                    with (
                        mock.patch("scripts.gar_lib.commands.target.resolve_workspace", return_value=self.workspace),
                        mock.patch("scripts.gar_lib.artifacts.store.PROJECT_ROOT", project_root),
                        mock.patch("scripts.gar_lib.api.target_lifecycle_for", return_value=mock.Mock()),
                        contextlib.redirect_stdout(output),
                        contextlib.redirect_stderr(errors),
                    ):
                        exit_code = main(["target", action, "--json", "--workspace", "Local/Product"])

                    payload = json.loads(output.getvalue())
                    self.assertEqual(1, exit_code)
                    self.assertFalse(payload["ok"])
                    self.assertIn("target_app artifact が壊れています", payload["error"])
                    self.assertIn("invalid artifact manifest JSON", payload["error"])
                    self.assertEqual("", errors.getvalue())

            output = io.StringIO()
            errors = io.StringIO()
            with (
                mock.patch("scripts.gar_lib.commands.target.resolve_workspace", return_value=self.workspace),
                mock.patch("scripts.gar_lib.artifacts.store.PROJECT_ROOT", project_root),
                mock.patch("scripts.gar_lib.api.target_lifecycle_for", return_value=mock.Mock()),
                contextlib.redirect_stdout(output),
                contextlib.redirect_stderr(errors),
            ):
                exit_code = main(["target", "status", "--workspace", "Local/Product"])

            self.assertEqual(1, exit_code)
            self.assertEqual("", output.getvalue())
            self.assertIn("invalid artifact manifest JSON", errors.getvalue())
            self.assertIn("target_app artifact が壊れています", errors.getvalue())

    def test_explicit_app_status_does_not_require_a_local_artifact(self) -> None:
        artifacts = mock.Mock()
        artifacts.latest.side_effect = AssertionError("latest artifact must not be read")
        lifecycle = mock.Mock()
        lifecycle.status.return_value = TargetLifecycleResult("status", "demo", 0, "running\n", "")

        with mock.patch("scripts.gar_lib.api.target_lifecycle_for", return_value=lifecycle):
            result = Gar(self.workspace, artifacts).target.status(app="demo")

        self.assertTrue(result.ok)
        lifecycle.status.assert_called_once_with(TargetApplication("demo"))
        artifacts.latest.assert_not_called()

    def test_api_deploy_validates_places_reloads_and_verifies_running_build(self) -> None:
        artifact = Artifact(ArtifactKind.TARGET_APP, self.workspace, Path("/tmp/artifact"))
        artifacts = mock.Mock()
        artifacts.latest.return_value = artifact
        environment = mock.Mock()
        lifecycle = mock.Mock()
        application = TargetApplication("demo", expected_build_id="build-123")
        lifecycle.reload.return_value = TargetLifecycleResult("reload", "demo", 0, "reloaded\n", "")
        lifecycle.diag.return_value = TargetDiagnosticReport(
            application=application,
            status=TargetLifecycleResult("status", "demo", 0, "running\n", ""),
            health=TargetLifecycleResult("health", "demo", 0, "healthy\n", ""),
            build_id=TargetLifecycleResult("running-build-id", "demo", 0, "build-123\n", ""),
        )

        with (
            mock.patch("scripts.gar_lib.api.target_environment_for", return_value=environment),
            mock.patch("scripts.gar_lib.api.target_lifecycle_for", return_value=lifecycle),
            mock.patch("scripts.gar_lib.api.target_application_from_artifact", return_value=application),
        ):
            result = Gar(self.workspace, artifacts).target.deploy_report()

        self.assertTrue(result.report.ok)
        environment.validate_deployment.assert_called_once_with(artifact)
        environment.deploy.assert_called_once_with(artifact)
        lifecycle.reload.assert_called_once_with(application)
        lifecycle.diag.assert_called_once_with(application)

    def test_api_deploy_raises_structured_convergence_error_after_placement(self) -> None:
        artifact = Artifact(ArtifactKind.TARGET_APP, self.workspace, Path("/tmp/artifact"))
        artifacts = mock.Mock()
        artifacts.latest.return_value = artifact
        environment = mock.Mock()
        lifecycle = mock.Mock()
        application = TargetApplication("demo", expected_build_id="build-new")
        lifecycle.reload.return_value = TargetLifecycleResult("reload", "demo", 1, "", "failed\n")
        lifecycle.diag.return_value = TargetDiagnosticReport(
            application=application,
            status=TargetLifecycleResult("status", "demo", 1, "", "not active\n"),
            health=TargetLifecycleResult("health", "demo", 1, "", "unhealthy\n"),
            build_id=TargetLifecycleResult("running-build-id", "demo", 1, "", "no build\n"),
        )

        with (
            mock.patch("scripts.gar_lib.api.target_environment_for", return_value=environment),
            mock.patch("scripts.gar_lib.api.target_lifecycle_for", return_value=lifecycle),
            mock.patch("scripts.gar_lib.api.target_application_from_artifact", return_value=application),
            self.assertRaises(TargetDeploymentConvergenceError) as caught,
        ):
            Gar(self.workspace, artifacts).target.deploy_report()

        self.assertTrue(caught.exception.report.placed)
        self.assertFalse(caught.exception.report.running)
        environment.deploy.assert_called_once_with(artifact)

    def test_register_failure_after_complete_placement_is_structured(self) -> None:
        artifact = Artifact(ArtifactKind.TARGET_APP, self.workspace, Path("/tmp/artifact"))
        artifacts = mock.Mock()
        artifacts.latest.return_value = artifact
        environment = mock.Mock()
        environment.deploy.side_effect = TargetPlacementError(
            "register-app failed",
            placed_destinations=("/opt/gar/apps/demo", "/etc/gar/demo.env"),
            placement_complete=True,
        )
        lifecycle = mock.Mock()
        application = TargetApplication("demo", expected_build_id="build-new")

        with (
            mock.patch("scripts.gar_lib.api.target_environment_for", return_value=environment),
            mock.patch("scripts.gar_lib.api.target_lifecycle_for", return_value=lifecycle),
            mock.patch("scripts.gar_lib.api.target_application_from_artifact", return_value=application),
            self.assertRaises(TargetDeploymentConvergenceError) as caught,
        ):
            Gar(self.workspace, artifacts).target.deploy_report()

        report = caught.exception.report
        self.assertTrue(report.placed)
        self.assertFalse(report.partial)
        self.assertFalse(report.running)
        self.assertEqual("register-app failed", report.failure)
        lifecycle.reload.assert_not_called()

    def test_reload_exception_after_placement_is_structured(self) -> None:
        artifact = Artifact(ArtifactKind.TARGET_APP, self.workspace, Path("/tmp/artifact"))
        artifacts = mock.Mock()
        artifacts.latest.return_value = artifact
        environment = mock.Mock()
        lifecycle = mock.Mock()
        lifecycle.reload.side_effect = AccessConnectionError(
            channel="ssh",
            endpoint="target",
            reason="connection_refused",
            returncode=255,
        )
        application = TargetApplication("demo", expected_build_id="build-new")

        with (
            mock.patch("scripts.gar_lib.api.target_environment_for", return_value=environment),
            mock.patch("scripts.gar_lib.api.target_lifecycle_for", return_value=lifecycle),
            mock.patch("scripts.gar_lib.api.target_application_from_artifact", return_value=application),
            self.assertRaises(TargetDeploymentConvergenceError) as caught,
        ):
            Gar(self.workspace, artifacts).target.deploy_report()

        report = caught.exception.report
        self.assertTrue(report.placed)
        self.assertFalse(report.partial)
        self.assertFalse(report.running)
        self.assertIn("connection failed", report.failure or "")

    def test_deploy_json_failure_reports_placed_but_not_running_and_nonzero(self) -> None:
        application = TargetApplication("demo", expected_build_id="build-new")
        diagnostic = TargetDiagnosticReport(
            application=application,
            status=TargetLifecycleResult("status", "demo", 1, "", "not active\n"),
            health=TargetLifecycleResult("health", "demo", 1, "", "unhealthy\n"),
            build_id=TargetLifecycleResult("running-build-id", "demo", 1, "", "no build\n"),
        )
        report = TargetDeploymentReport(
            application=application,
            artifact_path="/tmp/artifact",
            placed=True,
            diagnostic=diagnostic,
            verification="lifecycle-v1",
        )
        target_api = mock.Mock()
        target_api.deploy_report.side_effect = TargetDeploymentConvergenceError(report)
        output = io.StringIO()

        with (
            mock.patch("scripts.gar_lib.commands.target.resolve_workspace", return_value=self.workspace),
            mock.patch("scripts.gar_lib.commands.target.Gar", return_value=mock.Mock(target=target_api)),
            contextlib.redirect_stdout(output),
        ):
            exit_code = main(["target", "deploy", "--json", "--workspace", "Local/Product"])

        payload = json.loads(output.getvalue())
        self.assertEqual(1, exit_code)
        self.assertTrue(payload["placed"])
        self.assertFalse(payload["running"])
        self.assertFalse(payload["ok"])
        self.assertEqual({"available": False, "attempted": False}, payload["rollback"])

    def test_deploy_json_reports_partial_destinations_truthfully(self) -> None:
        report = TargetDeploymentReport(
            application=TargetApplication("demo", expected_build_id="build-new"),
            artifact_path="/tmp/artifact",
            placed=True,
            partial=True,
            placed_destinations=("/opt/gar/apps/demo",),
            failure="environment install failed",
            verification="lifecycle-v1",
        )
        target_api = mock.Mock()
        target_api.deploy_report.side_effect = TargetDeploymentConvergenceError(report)
        output = io.StringIO()

        with (
            mock.patch("scripts.gar_lib.commands.target.resolve_workspace", return_value=self.workspace),
            mock.patch("scripts.gar_lib.commands.target.Gar", return_value=mock.Mock(target=target_api)),
            contextlib.redirect_stdout(output),
        ):
            exit_code = main(["target", "deploy", "--json", "--workspace", "Local/Product"])

        payload = json.loads(output.getvalue())
        self.assertEqual(1, exit_code)
        self.assertTrue(payload["placed"])
        self.assertTrue(payload["partial"])
        self.assertFalse(payload["running"])
        self.assertEqual(["/opt/gar/apps/demo"], payload["placed_destinations"])
        self.assertEqual("environment install failed", payload["error"])

    def test_json_post_placement_access_failure_does_not_start_recovery(self) -> None:
        report = TargetDeploymentReport(
            application=TargetApplication("demo", expected_build_id="build-new"),
            artifact_path="/tmp/artifact",
            placed=True,
            placed_destinations=("/opt/gar/apps/demo",),
            failure="ssh connection failed after placement",
            verification="lifecycle-v1",
        )
        target_api = mock.Mock()
        target_api.deploy_report.side_effect = convergence_with_access_failure(report)
        output = io.StringIO()
        errors = io.StringIO()

        with (
            mock.patch("scripts.gar_lib.commands.target.resolve_workspace", return_value=self.workspace),
            mock.patch("scripts.gar_lib.commands.target.Gar", return_value=mock.Mock(target=target_api)),
            mock.patch("scripts.gar_lib.commands.target.run_terminal_run_command") as run_terminal,
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
        ):
            exit_code = main(["target", "deploy", "--json", "--workspace", "Local/Product"])

        payload = json.loads(output.getvalue())
        self.assertEqual(1, exit_code)
        self.assertTrue(payload["placed"])
        self.assertFalse(payload["running"])
        self.assertEqual("", errors.getvalue())
        run_terminal.assert_not_called()

    def test_non_json_post_placement_access_failure_keeps_state_and_starts_recovery(self) -> None:
        report = TargetDeploymentReport(
            application=TargetApplication("demo", expected_build_id="build-new"),
            artifact_path="/tmp/artifact",
            placed=True,
            placed_destinations=("/opt/gar/apps/demo",),
            failure="ssh connection failed after placement",
            verification="lifecycle-v1",
        )
        target_api = mock.Mock()
        target_api.deploy.side_effect = convergence_with_access_failure(report)
        output = io.StringIO()
        errors = io.StringIO()

        with (
            mock.patch("scripts.gar_lib.commands.target.resolve_workspace", return_value=self.workspace),
            mock.patch("scripts.gar_lib.commands.target.Gar", return_value=mock.Mock(target=target_api)),
            mock.patch("scripts.gar_lib.commands.target.run_terminal_run_command") as run_terminal,
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
        ):
            exit_code = main(["target", "deploy", "--workspace", "Local/Product"])

        self.assertEqual(1, exit_code)
        self.assertIn("Placement: complete", output.getvalue())
        self.assertIn("Target lifecycle権限の準備", str(run_terminal.call_args))
        self.assertIn("target_prepare_required", errors.getvalue())

    def test_deploy_json_domain_error_is_still_structured_and_nonzero(self) -> None:
        target_api = mock.Mock()
        target_api.deploy_report.side_effect = GarDomainError("artifact compatibility rejected")
        output = io.StringIO()

        with (
            mock.patch("scripts.gar_lib.commands.target.resolve_workspace", return_value=self.workspace),
            mock.patch("scripts.gar_lib.commands.target.Gar", return_value=mock.Mock(target=target_api)),
            contextlib.redirect_stdout(output),
        ):
            exit_code = main(["target", "deploy", "--json", "--workspace", "Local/Product"])

        payload = json.loads(output.getvalue())
        self.assertEqual(1, exit_code)
        self.assertFalse(payload["placed"])
        self.assertFalse(payload["running"])
        self.assertFalse(payload["ok"])

    def test_json_connection_error_has_no_human_recovery_or_terminal_side_effect(self) -> None:
        target_api = mock.Mock()
        target_api.status.side_effect = AccessConnectionError(
            channel="ssh",
            endpoint="target",
            reason="target_prepare_required",
            returncode=255,
        )
        output = io.StringIO()
        errors = io.StringIO()

        with (
            mock.patch("scripts.gar_lib.commands.target.resolve_workspace", return_value=self.workspace),
            mock.patch("scripts.gar_lib.commands.target.Gar", return_value=mock.Mock(target=target_api)),
            mock.patch("scripts.gar_lib.commands.target.report_access_failure") as report_failure,
            mock.patch("scripts.gar_lib.commands.target.run_terminal_run_command") as run_terminal,
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
        ):
            exit_code = main(["target", "status", "--json", "--workspace", "Local/Product"])

        payload = json.loads(output.getvalue())
        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual("ssh", payload["channel"])
        self.assertEqual("target_prepare_required", payload["reason"])
        self.assertEqual(1, payload["exit_code"])
        self.assertEqual(255, payload["backend_exit_code"])
        self.assertEqual("", errors.getvalue())
        report_failure.assert_not_called()
        run_terminal.assert_not_called()


if __name__ == "__main__":
    unittest.main()
