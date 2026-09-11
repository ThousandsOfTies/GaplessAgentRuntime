from __future__ import annotations

import contextlib
import io
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.gar_lib.access.channel import AccessResult
from scripts.gar_lib.access.display import run_displayed
from scripts.gar_lib.api import Gar
from scripts.gar_lib.cli import build_parser, main
from scripts.gar_lib.commands.code_observation import code_logs, observe_code, prepare_code
from scripts.gar_lib.commands.code_state import CodespaceConnectionState
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.capabilities import COMMON_ACTIONS, command_capabilities
from scripts.gar_lib.core.errors import AccessConnectionError, GarDomainError
from scripts.gar_lib.core.observation import EnvironmentObservation, component, unavailable
from scripts.gar_lib.core.output import JSON_OUTPUT
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.simulation.host.prepare import prepare_simulation_host
from scripts.gar_lib.simulation.observation import observe_simulation
from scripts.gar_lib.simulation.runtime.linux_commands import LinuxSystemdCommandBuilder
from scripts.gar_lib.simulation.runtime.linux_systemd import LinuxSystemdSimulationEnvironment
from scripts.gar_lib.simulation.runtime.mujoco import MujocoSimulationEnvironment
from scripts.gar_lib.simulation.runtime.wokwi import WokwiSimulationEnvironment
from scripts.gar_lib.target.lifecycle import CommandTargetLifecycle, TargetApplication
from scripts.gar_lib.target.manifest import TargetLifecycleCapability
from scripts.gar_lib.target.ssh_prepare import prepare_ssh_target


def workspace(
    root: Path | str = "/test/product", *, code: str = "local", sim: str = "local_docker", target: str = "ssh_scp"
) -> Workspace:
    return Workspace(
        id="surface",
        name="Local/Product",
        branch="main",
        connection={"type": "local", "path": str(root)},
        selected_environments={"codespace": code, "simulator": sim, "target": target},
        simulation_host={"provider": "virtualbox", "host": "sim-test"},
    )


class CommonResultTest(unittest.TestCase):
    def test_json_in_application_logs_is_content_not_a_command_result(self) -> None:
        with (
            mock.patch(
                "scripts.gar_lib.commands.code.resolve_workspace", return_value=workspace(code="github_codespaces")
            ),
            mock.patch("scripts.gar_lib.commands.code.code_logs") as log,
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            log.side_effect = lambda *args, **kwargs: (print('{"ok":false,"workspace":"unrelated"}'), 0)[1]
            self.assertEqual(0, main(["code", "log", "--json"]))
            result = json.loads(out.getvalue())
        self.assertTrue(result["ok"])
        self.assertEqual("Local/Product", result["workspace"])
        self.assertIn('"workspace":"unrelated"', result["output"])

    def test_common_options_work_before_or_after_action(self) -> None:
        parser = build_parser()
        for group in ("code", "sim", "target"):
            for action in ("prepare", "start", "stop", "status", "diag"):
                for options_first in (False, True):
                    with self.subTest(group=group, action=action, options_first=options_first):
                        options = ["--workspace", "Local/Product", "--json"]
                        args = parser.parse_args(
                            [group, *options, action] if options_first else [group, action, *options]
                        )
                        self.assertEqual("Local/Product", args.workspace)
                        self.assertTrue(args.json_output)

    def test_workspace_errors_are_one_json_document_for_all_groups(self) -> None:
        for group in ("code", "sim", "target"):
            with (
                self.subTest(group=group),
                mock.patch(
                    f"scripts.gar_lib.commands.{group}.resolve_workspace",
                    side_effect=GarDomainError("missing workspace"),
                ),
                contextlib.redirect_stdout(io.StringIO()) as out,
                contextlib.redirect_stderr(io.StringIO()) as err,
            ):
                self.assertEqual(1, main([group, "status", "--json"]))
                payload = json.loads(out.getvalue())
                self.assertEqual(f"{group}.status", payload["command"])
                self.assertFalse(payload["ok"])
                self.assertEqual(1, payload["exit_code"])
                self.assertIn("missing workspace", payload["error"])
                self.assertEqual("", err.getvalue())

    def test_unsupported_infra_json_is_rejected_before_infrastructure_operations(self) -> None:
        with (
            mock.patch("scripts.gar_lib.commands.sim.run_sim_infra_command") as infra,
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            self.assertEqual(1, main(["sim", "--json", "infra", "apply"]))
            self.assertFalse(json.loads(out.getvalue())["ok"])
        infra.assert_not_called()

    def test_child_output_cannot_corrupt_json_or_override_structured_result(self) -> None:
        ws = workspace()

        def deploy():
            run_displayed(
                [sys.executable, "-c", "import sys; print('build progress'); print('tool diagnostic', file=sys.stderr)"]
            )
            return (Artifact(ArtifactKind.SIM_APP, ws, Path("snapshot")),)

        with (
            mock.patch("scripts.gar_lib.commands.sim.resolve_workspace", return_value=ws),
            mock.patch("scripts.gar_lib.commands.sim.Gar") as factory,
            contextlib.redirect_stdout(io.StringIO()) as out,
            contextlib.redirect_stderr(io.StringIO()) as err,
        ):
            factory.return_value.sim.deploy.side_effect = deploy
            self.assertEqual(0, main(["sim", "deploy", "--json"]))
            result = json.loads(out.getvalue())
        self.assertTrue(result["placed"])
        self.assertIsNone(result["running"])
        self.assertEqual("not_checked", result["verification"])
        self.assertIn("build progress", result["output"])
        self.assertIn("tool diagnostic", result["diagnostics"])
        self.assertEqual("", err.getvalue())

    def test_sim_partial_failure_reports_completed_and_uncertain_placement(self) -> None:
        ws = workspace()
        artifacts = [Artifact(kind, ws, Path(kind.value)) for kind in (ArtifactKind.SIM_RUNTIME, ArtifactKind.SIM_APP)]
        store = mock.Mock()
        store.latest.side_effect = artifacts
        with (
            mock.patch("scripts.gar_lib.api.simulation_environment_for") as env,
            mock.patch("scripts.gar_lib.api._validate_simulation_architecture"),
            mock.patch("scripts.gar_lib.commands.sim.resolve_workspace", return_value=ws),
            mock.patch("scripts.gar_lib.commands.sim.Gar", return_value=Gar(ws, store)),
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            env.return_value.requires_runtime_artifact = True
            env.return_value.deploy.side_effect = [None, GarDomainError("transfer interrupted")]
            self.assertEqual(1, main(["sim", "deploy", "--json"]))
            result = json.loads(out.getvalue())
        self.assertTrue(result["partial"])
        self.assertEqual("sim_runtime", result["placed_artifacts"][0]["kind"])
        self.assertEqual("sim_app", result["failed_artifact"]["kind"])
        self.assertTrue(result["failed_artifact_may_be_partial"])
        self.assertFalse(result["rollback"]["attempted"])
        env.return_value.start.assert_not_called()

    def test_default_observation_uses_aggregate_but_explicit_runtime_keeps_legacy(self) -> None:
        ws = workspace()
        report = EnvironmentObservation("sim.status", ws.name, "local_docker", {"app": component("stopped", False)})
        with (
            mock.patch("scripts.gar_lib.commands.sim.resolve_workspace", return_value=ws),
            mock.patch("scripts.gar_lib.commands.sim.Gar") as factory,
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            factory.return_value.sim.status.return_value = report
            self.assertEqual(1, main(["sim", "status", "--json"]))
            factory.return_value.sim.runtime.status.assert_not_called()
            self.assertEqual("stopped", json.loads(out.getvalue())["components"]["app"]["state"])
            factory.return_value.sim.runtime.status.return_value = 0
            self.assertEqual(0, main(["sim", "status", "runtime", "--json"]))
            factory.return_value.sim.runtime.status.assert_called_once()


class ObservationTest(unittest.TestCase):
    def test_systemd_observation_is_read_only_and_identifies_empty_app_service(self) -> None:
        command = LinuxSystemdCommandBuilder().build_component_status({})
        script = shlex.split(command)[2]

        def probe(argv, **kwargs):
            self.assertEqual(["systemctl", "show"], argv[:2])
            executable = "/bin/true" if argv[2] == "gar-sim-app.service" else "/usr/bin/bridge"
            return subprocess.CompletedProcess(
                argv, 0, f"LoadState=loaded\nActiveState=active\nExecStart={{ path={executable} ; }}\n", ""
            )

        with mock.patch("subprocess.run", side_effect=probe), contextlib.redirect_stdout(io.StringIO()) as output:
            exec(script, {})
        channel = mock.Mock()
        channel.run.return_value = AccessResult((), 0, output.getvalue(), "")
        environment = LinuxSystemdSimulationEnvironment(channel, mock.Mock(), LinuxSystemdCommandBuilder())
        result = environment.observe({}, diagnostic=False)
        self.assertTrue(result["runtime"]["ok"])
        self.assertEqual("not_deployed", result["app"]["state"])
        self.assertFalse(result["app"]["ok"])
        self.assertTrue(result["connection"]["ok"])

    def test_malformed_service_output_preserves_evidence_of_reachable_connection(self) -> None:
        for output in ("garbage", "{}", '{"gar-sim-app.service": "bad"}'):
            with self.subTest(output=output):
                channel = mock.Mock()
                channel.run.return_value = AccessResult((), 0, output, "")
                result = LinuxSystemdSimulationEnvironment(channel, mock.Mock(), LinuxSystemdCommandBuilder()).observe(
                    {}, diagnostic=False
                )
                self.assertTrue(result["connection"]["ok"])
                self.assertFalse(result["runtime"]["ok"])
                self.assertFalse(result["app"]["ok"])

    def test_host_failure_does_not_hide_independent_runtime_observation(self) -> None:
        with (
            mock.patch("scripts.gar_lib.simulation.observation.simulation_host_for") as host,
            mock.patch("scripts.gar_lib.simulation.observation.simulation_environment_for") as env,
        ):
            host.return_value.status.side_effect = GarDomainError("provider inaccessible")
            env.return_value.observe.return_value = {
                "connection": component("reachable", True),
                "runtime": component("running", True),
                "app": component("running", True),
            }
            result = observe_simulation(workspace(), {}, diagnostic=False)
        self.assertFalse(result.ok)
        self.assertTrue(result.components["app"]["ok"])
        self.assertFalse(result.components["host"]["ok"])

    def test_connection_failure_does_not_claim_stopped_application(self) -> None:
        with (
            mock.patch("scripts.gar_lib.simulation.observation.simulation_host_for") as host,
            mock.patch("scripts.gar_lib.simulation.observation.simulation_environment_for") as env,
        ):
            host.return_value.status.return_value = mock.Mock(state="running", running=True, backend="virtualbox")
            env.return_value.observe.side_effect = AccessConnectionError(
                channel="ssh", endpoint="sim-test", reason="unreachable", returncode=255
            )
            result = observe_simulation(workspace(), {}, diagnostic=True)
        self.assertEqual("unreachable", result.components["connection"]["state"])
        self.assertEqual("unknown", result.components["app"]["state"])

    def test_local_simulator_readiness_is_not_process_liveness(self) -> None:
        for cls in (WokwiSimulationEnvironment, MujocoSimulationEnvironment):
            with self.subTest(backend=cls.__name__):
                environment = mock.Mock(spec=cls)
                environment.process_channel = mock.Mock()
                environment.identity = mock.Mock()
                environment.identity.observe.return_value = {
                    "build_id_match": False,
                    "build_id_verification": "stopped",
                }
                environment._state.return_value = {}
                environment.diag.return_value.exit_code = 0
                environment.diag.return_value.to_payload.return_value = {"ok": True}
                parts = cls.observe(environment, {}, diagnostic=True)
                self.assertFalse(parts["runtime"]["ok"])
                self.assertFalse(parts["app"]["ok"])
                self.assertIsNone(parts["connection"]["ok"])
                environment.process_channel.owns.assert_not_called()

    def test_not_applicable_is_explicit_and_not_an_error(self) -> None:
        result = EnvironmentObservation(
            "code.diag",
            "test",
            "local",
            {"connection": component("available", True), "app": unavailable("observed elsewhere")},
        )
        self.assertTrue(result.ok)
        self.assertIsNone(result.to_payload()["components"]["app"]["ok"])


class CodeEnvironmentTest(unittest.TestCase):
    def test_failed_ssh_probe_cannot_leave_a_configured_connection_successful(self) -> None:
        state = CodespaceConnectionState("ready", "codespace.ready", "/workspaces/product", Path("/test/mount"))
        with (
            mock.patch("scripts.gar_lib.commands.code_observation.CodespaceConnectionState.load", return_value=state),
            mock.patch("scripts.gar_lib.commands.code_observation.run_gh_captured") as gh,
        ):
            gh.side_effect = [
                subprocess.CompletedProcess([], 0, '[{"name":"ready","state":"Available"}]', ""),
                OSError("connection lost"),
            ]
            result = observe_code(workspace(code="github_codespaces"), action="diag", codespace="ready")
        self.assertFalse(result.ok)
        self.assertTrue(result.components["host"]["ok"])
        self.assertFalse(result.components["connection"]["ok"])

    def test_stopped_codespace_is_not_probed_over_ssh_or_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = CodespaceConnectionState(
                "sleeping", "codespace.sleeping", "/workspaces/product", Path(tmp) / "mount"
            )
            state.write(path)
            before = path.read_bytes()
            with (
                mock.patch("scripts.gar_lib.commands.code_observation.codespace_state_path", return_value=path),
                mock.patch(
                    "scripts.gar_lib.commands.code_observation.run_gh_captured",
                    return_value=subprocess.CompletedProcess([], 0, '[{"name":"sleeping","state":"Shutdown"}]', ""),
                ) as gh,
            ):
                result = observe_code(workspace(code="github_codespaces"), action="diag", codespace="sleeping")
            self.assertFalse(result.ok)
            self.assertEqual("shutdown", result.components["host"]["state"])
            self.assertEqual(1, gh.call_count)
            self.assertEqual(before, path.read_bytes())

    def test_invalid_state_and_malformed_provider_response_do_not_rewrite_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text("broken state", encoding="utf-8")
            with (
                mock.patch("scripts.gar_lib.commands.code_observation.codespace_state_path", return_value=path),
                mock.patch(
                    "scripts.gar_lib.commands.code_observation.run_gh_captured",
                    return_value=subprocess.CompletedProcess([], 0, '["bad row"]', ""),
                ),
            ):
                result = observe_code(workspace(code="github_codespaces"), action="diag")
            self.assertFalse(result.ok)
            self.assertEqual("broken state", path.read_text(encoding="utf-8"))

    def test_local_prepare_checks_existing_workspace_without_creating_it(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch("scripts.gar_lib.commands.code_observation.shutil.which", return_value="git"),
        ):
            missing = Path(tmp) / "missing"
            self.assertFalse(prepare_code(workspace(missing)).ok)
            self.assertFalse(missing.exists())
            self.assertTrue(prepare_code(workspace(tmp)).ok)

    def test_local_code_log_is_rejected_without_external_process(self) -> None:
        with (
            mock.patch("scripts.gar_lib.commands.code_observation.run_gh_captured") as gh,
            self.assertRaises(GarDomainError),
        ):
            code_logs(workspace())
        gh.assert_not_called()


class PreparationAndCapabilityTest(unittest.TestCase):
    def test_target_json_prepare_never_stages_before_noninteractive_privilege_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("prepare.sh", "gar-target-install", "gar-app@.service", "gar-target-lifecycle"):
                (root / name).write_text("recipe", encoding="utf-8")
            with mock.patch("scripts.gar_lib.target.ssh_prepare.subprocess.run") as run:
                run.side_effect = [
                    subprocess.CompletedProcess([], 0, "user\n", ""),
                    subprocess.CompletedProcess([], 1, "", "password required"),
                ]
                token = JSON_OUTPUT.set(True)
                try:
                    with self.assertRaisesRegex(GarDomainError, "非対話sudo"):
                        prepare_ssh_target(
                            "target-test",
                            root,
                            target_id="test",
                            recipe_version="1",
                            gar_tools_commit="a" * 40,
                            include_lifecycle=True,
                        )
                finally:
                    JSON_OUTPUT.reset(token)
            self.assertEqual(2, run.call_count)
            self.assertIn("sudo -n", run.call_args.args[0][-1])

    def test_stop_and_status_use_selected_bridge_port(self) -> None:
        for action in ("stop", "status"):
            with (
                self.subTest(action=action),
                mock.patch("scripts.gar_lib.api.simulation_environment_for") as environment,
                mock.patch("scripts.gar_lib.api._workspace_hardware", return_value={}),
                mock.patch(
                    "scripts.gar_lib.simulation.session.remote.subprocess.run",
                    return_value=subprocess.CompletedProcess([], 0),
                ) as run,
            ):
                environment.return_value.session_host = "sim-test"
                getattr(environment.return_value, action).return_value = 0
                self.assertEqual(0, getattr(Gar(workspace()).sim.runtime, action)(panel_port=8081))
                command = run.call_args.args[0]
                self.assertIn("--" + action, command)
                self.assertEqual("8081", command[command.index("--http") + 1])

    def test_target_manifest_rejects_non_boolean_stop_capability(self) -> None:
        from scripts.gar_lib.target.manifest import _validate_lifecycle_capability

        for value in ("true", 1, None):
            issues = []
            result = _validate_lifecycle_capability(
                {"type": "gar-app-lifecycle-v1", "command": "/usr/local/lib/gar/helper", "stop": value},
                Path("target.json"),
                "provisioning.ssh_scp",
                issues,
            )
            self.assertIsNone(result)
            self.assertEqual("provisioning.ssh_scp.lifecycle.stop", issues[0].field)

    def test_capability_query_is_read_only_and_preserves_common_vocabulary(self) -> None:
        with (
            mock.patch("scripts.gar_lib.commands.capabilities.resolve_workspace", return_value=workspace(sim="wokwi")),
            mock.patch("scripts.gar_lib.simulation.composition.simulation_environment_for") as env,
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            self.assertEqual(0, main(["sim", "--capabilities", "--json"]))
            result = json.loads(out.getvalue())
        self.assertEqual(set(COMMON_ACTIONS), set(result["actions"]))
        self.assertFalse(result["actions"]["prepare"])
        self.assertTrue(result["actions"]["start"])
        env.assert_not_called()

    def test_capabilities_cannot_swallow_a_requested_action(self) -> None:
        with (
            mock.patch("scripts.gar_lib.commands.capabilities.resolve_workspace") as resolve,
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            self.assertEqual(1, main(["sim", "--capabilities", "start", "--json"]))
            self.assertFalse(json.loads(out.getvalue())["ok"])
        resolve.assert_not_called()

    def test_target_stop_capability_is_opt_in(self) -> None:
        for supported in (False, True):
            with (
                self.subTest(supported=supported),
                mock.patch("scripts.gar_lib.core.capabilities._selected_target_manifest") as selected,
            ):
                selected.return_value.lifecycle_capability.return_value = TargetLifecycleCapability(
                    "gar-app-lifecycle-v1", "/usr/local/lib/gar/helper", supported
                )
                report = command_capabilities("target", workspace())
                self.assertIs(supported, report["actions"]["stop"])

    def test_unsupported_sim_prepare_fails_before_host_or_transfer(self) -> None:
        with (
            mock.patch("scripts.gar_lib.simulation.host.prepare.simulation_host_for") as host,
            mock.patch("scripts.gar_lib.simulation.host.prepare.SshCommandChannel") as ssh,
        ):
            for backend in ("wokwi", "mujoco", "renode_mcu"):
                with self.subTest(backend=backend), self.assertRaises(GarDomainError):
                    prepare_simulation_host(workspace(sim=backend))
            host.assert_not_called()
            ssh.assert_not_called()

    def test_ssh_sim_prepare_rejects_missing_privilege_before_transfer(self) -> None:
        with (
            mock.patch("scripts.gar_lib.simulation.host.prepare.SshCommandChannel") as ssh,
            mock.patch("scripts.gar_lib.simulation.host.prepare.ScpFileChannel") as scp,
        ):
            ssh.return_value.run.return_value = AccessResult((), 1, "", "sudo required")
            with self.assertRaises(GarDomainError):
                prepare_simulation_host(workspace(sim="ssh_remote"))
            scp.assert_not_called()
            self.assertEqual(1, ssh.return_value.run.call_count)

    def test_stop_unsupported_recipe_is_rejected_before_any_remote_command(self) -> None:
        channel = mock.Mock()
        lifecycle = CommandTargetLifecycle(channel, "/usr/local/lib/gar/helper")
        with self.assertRaises(GarDomainError):
            lifecycle.stop(TargetApplication("demo"))
        channel.run.assert_not_called()

    def test_stop_uses_recipe_and_preserves_failure_exit_code(self) -> None:
        channel = mock.Mock()
        channel.run.side_effect = [AccessResult((), 0, "0\n", ""), AccessResult((), 7, "", "could not stop")]
        result = CommandTargetLifecycle(channel, "/usr/local/lib/gar/helper", supports_stop=True).stop(
            TargetApplication("demo")
        )
        self.assertFalse(result.ok)
        self.assertEqual(1, result.exit_code)
        self.assertEqual(7, result.returncode)
        self.assertEqual("/usr/local/lib/gar/helper stop demo", channel.run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
