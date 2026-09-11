from __future__ import annotations

import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest import mock

from scripts.gar_lib.api import Gar
from scripts.gar_lib.cli import main
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.capabilities import command_capabilities
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.simulation.host.prepare import prepare_simulation_host
from scripts.gar_lib.target.lifecycle import TargetApplication, TargetDeploymentConvergenceError, TargetLifecycleResult


def workspace(sim: str | None, *, code: str = "native", target: str = "ssh_scp") -> Workspace:
    return Workspace(
        id="boundary",
        name="Local/Boundary",
        branch="main",
        connection={"type": "local", "path": "/test/product"},
        selected_environments={"codespace": code, "simulator": sim, "target": target},
    )


class SimulationCapabilityBoundaryTest(unittest.TestCase):
    def test_unsupported_backends_do_not_compose_tools_or_touch_artifacts(self) -> None:
        for backend in (None, "unknown", "aws_ssm", "renode_mcu", "esp32_qemu_firmware"):
            ws = workspace(backend)
            artifacts = mock.Mock()
            sim = Gar(ws, artifacts).sim
            actions = {
                "prepare": lambda ws=ws: prepare_simulation_host(ws),
                "build": sim.build,
                "deploy": sim.deploy,
                "status": sim.status,
                "diag": sim.diag,
                "build app": sim.app.build,
                "clean app": sim.app.clean,
                "deploy app": sim.app.deploy,
                "build runtime": sim.runtime.build,
                "deploy runtime": sim.runtime.deploy,
                "start": sim.runtime.start,
                "stop": sim.runtime.stop,
                "status runtime": sim.runtime.status,
                "diag runtime": sim.runtime.diag,
                "log": sim.runtime.log,
            }
            with contextlib.ExitStack() as stack:
                guards = [
                    stack.enter_context(mock.patch(name))
                    for name in (
                        "scripts.gar_lib.api.build_environment_for",
                        "scripts.gar_lib.api.simulation_environment_for",
                        "scripts.gar_lib.api.observe_simulation",
                        "scripts.gar_lib.api.VsCodeSimulationSessionManager",
                        "scripts.gar_lib.api.load_hw_definition",
                        "scripts.gar_lib.simulation.host.prepare.simulation_host_for",
                        "scripts.gar_lib.simulation.host.prepare.SshCommandChannel",
                        "scripts.gar_lib.simulation.host.prepare.ScpFileChannel",
                    )
                ]
                self.assertFalse(any(command_capabilities("sim", ws)["actions"].values()))
                for action, execute in actions.items():
                    with self.subTest(backend=backend, action=action), self.assertRaisesRegex(GarDomainError, "未対応"):
                        execute()
                artifacts.latest.assert_not_called()
                for guard in guards:
                    guard.assert_not_called()

    def test_canonical_and_legacy_builds_return_the_same_json_failure(self) -> None:
        ws = workspace("renode_mcu")
        paths = (("build",), ("build", "app"), ("app", "build"), ("build", "runtime"), ("runtime", "build"))
        for path in paths:
            with (
                self.subTest(path=path),
                mock.patch("scripts.gar_lib.commands.sim.resolve_workspace", return_value=ws),
                mock.patch("scripts.gar_lib.api.build_environment_for") as build,
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(1, main(["sim", *path, "--json"]))
                result = json.loads(output.getvalue())
            self.assertFalse(result["ok"])
            self.assertEqual("sim.build", result["command"])
            self.assertIn("renode_mcu", result["error"])
            build.assert_not_called()

    def test_invalid_build_environment_is_rejected_before_simulator_composition(self) -> None:
        ws = workspace("ssh_remote", code="unsupported")
        sim = Gar(ws, mock.Mock()).sim
        self.assertFalse(command_capabilities("sim", ws)["actions"]["build"])
        with (
            mock.patch("scripts.gar_lib.api.build_environment_for") as build,
            mock.patch("scripts.gar_lib.api.simulation_environment_for") as runtime,
        ):
            for action in (sim.build, sim.app.build, sim.runtime.build, sim.app.clean):
                with self.assertRaisesRegex(GarDomainError, "BuildEnvironment"):
                    action()
        build.assert_not_called()
        runtime.assert_not_called()

    def test_runtimeless_backends_keep_optional_runtime_artifact_compatibility(self) -> None:
        for backend in ("wokwi", "mujoco"):
            ws = workspace(backend)
            artifacts = mock.Mock()
            with self.subTest(backend=backend), mock.patch("scripts.gar_lib.api.build_environment_for") as build:
                runtime = Gar(ws, artifacts).sim.runtime
                self.assertIsNone(runtime.build())
                self.assertIsNone(runtime.deploy())
            build.assert_not_called()
            artifacts.latest.assert_not_called()

    def test_explicit_host_action_is_independent_of_pending_runtime(self) -> None:
        with mock.patch("scripts.gar_lib.api.simulation_host_for") as host:
            Gar(workspace("aws_ssm")).sim.host.start()
        host.return_value.start.assert_called_once_with(update_address=True, update_repository=False)


class TargetCapabilityBoundaryTest(unittest.TestCase):
    def test_flash_targets_reject_application_actions_before_artifacts_and_connections(self) -> None:
        for backend in ("esp32_esptool", "uuu"):
            artifacts = mock.Mock()
            target = Gar(workspace(None, target=backend), artifacts).target
            with mock.patch("scripts.gar_lib.api.target_environment_for") as environment:
                for action in (target.start, target.stop, target.status, target.log, target.diag):
                    with (
                        self.subTest(backend=backend, action=action.__name__),
                        self.assertRaisesRegex(GarDomainError, "lifecycle capability"),
                    ):
                        action()
            artifacts.latest.assert_not_called()
            environment.assert_not_called()

    def test_failed_start_and_deploy_name_the_operation_that_was_attempted(self) -> None:
        ws = workspace(None)
        artifacts = mock.Mock()
        artifacts.latest.return_value = Artifact(ArtifactKind.TARGET_APP, ws, Path("snapshot"))
        application = TargetApplication("demo", expected_build_id="expected")
        for action, message in (("start", "start稼働確認"), ("deploy_report", "配置済み")):
            with (
                self.subTest(action=action),
                mock.patch("scripts.gar_lib.api.target_environment_for") as environment,
                mock.patch("scripts.gar_lib.api.target_lifecycle_for") as lifecycle,
                mock.patch("scripts.gar_lib.api.target_application_from_artifact", return_value=application),
            ):
                lifecycle.return_value.reload.return_value = TargetLifecycleResult("reload", "demo", 1, "", "failed")
                with self.assertRaisesRegex(TargetDeploymentConvergenceError, message):
                    getattr(Gar(ws, artifacts).target, action)()
                if action == "start":
                    environment.return_value.deploy.assert_not_called()
                else:
                    environment.return_value.deploy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
