from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.gar_lib.artifacts.metadata import ArtifactMetadata, sha256_checksums, write_artifact_metadata
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.simulation.observation import observe_simulation
from scripts.gar_lib.simulation.runtime import identity
from scripts.gar_lib.simulation.runtime.deployment import deployment_record, remote_deployment_command
from scripts.gar_lib.simulation.runtime.linux_commands import LinuxSystemdCommandBuilder
from scripts.gar_lib.simulation.runtime.linux_systemd import LinuxSystemdSimulationEnvironment
from scripts.gar_lib.simulation.runtime.mujoco import MujocoSimulationEnvironment
from scripts.gar_lib.simulation.runtime.process import ManagedProcess
from scripts.gar_lib.simulation.runtime.wokwi import WokwiSimulationEnvironment


def snapshot(root: Path, build: str, contents: dict[str, str]) -> Artifact:
    root.mkdir(parents=True)
    files = []
    for name, content in contents.items():
        source = root / "files" / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(content, encoding="utf-8")
        files.append({"src": "files/" + name, "dest": name})
    (root / "artifact.json").write_text(json.dumps({"deploy": {"app": {"files": files}}}), encoding="utf-8")
    metadata = ArtifactMetadata(
        2, ArtifactKind.SIM_APP.value, "test", build, "2026-09-11T00:00:00Z", checksums=sha256_checksums(root)
    )
    write_artifact_metadata(root, metadata)
    workspace = Workspace(
        "test", "Local/Test", "Test", {"type": "local", "path": str(root)}, selected_environments={"simulator": "wokwi"}
    )
    return Artifact(ArtifactKind.SIM_APP, workspace, root)


class SimulationIdentityTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.deployed, self.running = self.root / "deployed.json", self.root / "running.json"
        app = self.root / "app"
        app.write_text("A", encoding="utf-8")
        self.record = {
            "schema_version": 1,
            "state": "ready",
            "build_id": "A",
            "generation": "first",
            "files": {str(app): identity.digest(app)},
        }
        self.service = {
            "loaded": True,
            "active": True,
            "exit_code": 0,
            "placeholder": False,
            "pid": 123,
            "start_time_ticks": 42,
            "invocation_id": "first-start",
        }
        identity.write_record(self.deployed, self.record)
        identity.write_record(self.running, {"build_id": "A", "process": identity.service_identity(self.service)})

    def test_deploy_does_not_relabel_running_process_and_stop_invalidates_running_id(self):
        self.assertTrue(identity.observe_service(self.service, self.deployed, self.running)["build_id_match"])
        identity.write_record(self.deployed, {**self.record, "build_id": "B"})
        result = identity.observe_service(self.service, self.deployed, self.running)
        self.assertEqual(
            ("B", "A", "mismatch"),
            (result["expected_build_id"], result["running_build_id"], result["build_id_verification"]),
        )
        stopped = identity.observe_service({**self.service, "active": False, "pid": 0}, self.deployed, self.running)
        self.assertIsNone(stopped["running_build_id"])

    def test_pid_reuse_missing_birth_and_external_restart_cannot_reuse_receipt(self):
        for changes in (
            {"pid": 456},
            {"start_time_ticks": 43},
            {"start_time_ticks": None},
            {"invocation_id": "restart"},
            {"placeholder": True},
        ):
            with self.subTest(changes=changes):
                result = identity.observe_service({**self.service, **changes}, self.deployed, self.running)
                self.assertFalse(result["build_id_match"])
                self.assertIsNone(result["running_build_id"])

    def test_failed_start_and_concurrent_deploy_do_not_certify_app(self):
        for result_code, change in ((7, False), (0, True)):

            def start(_command, change=change, result_code=result_code):
                if change:
                    identity.write_record(self.deployed, {**self.record, "generation": "new"})
                return result_code

            with (
                mock.patch.object(identity.subprocess, "call", side_effect=start),
                mock.patch.object(identity, "service_state", return_value=self.service),
                mock.patch.object(identity, "process_uses_artifact", return_value=True),
            ):
                self.assertEqual(result_code, identity.start_service("runtime-start", self.deployed, self.running))
            self.assertNotIn("build_id", identity.read_record(self.running))

    def test_successful_start_binds_build_to_actual_service_invocation(self):
        with (
            mock.patch.object(identity.subprocess, "call", return_value=0),
            mock.patch.object(identity, "service_state", return_value=self.service),
            mock.patch.object(identity, "process_uses_artifact", return_value=True),
        ):
            self.assertEqual(0, identity.start_service("runtime-start", self.deployed, self.running))
        self.assertTrue(identity.observe_service(self.service, self.deployed, self.running)["build_id_match"])

    def test_unrelated_process_or_changed_files_do_not_certify_app(self):
        with (
            mock.patch.object(identity.subprocess, "call", return_value=0),
            mock.patch.object(identity, "service_state", return_value=self.service),
            mock.patch.object(identity, "process_uses_artifact", return_value=False),
        ):
            identity.start_service("runtime-start", self.deployed, self.running)
        self.assertFalse(identity.observe_service(self.service, self.deployed, self.running)["build_id_match"])
        (self.root / "app").write_text("changed", encoding="utf-8")
        self.assertFalse(identity.verified(self.record))

    def test_corrupt_and_legacy_receipts_never_match(self):
        for content in ("{", '{"schema_version": 2, "build_id": "A"}', "{}"):
            self.deployed.write_text(content, encoding="utf-8")
            self.assertFalse(identity.observe_service(self.service, self.deployed, self.running)["build_id_match"])

    def test_snapshot_checksum_failure_is_rejected_before_remote_effects(self):
        artifact = snapshot(self.root / "bad", "A", {"app": "binary"})
        (artifact.bundle_path / "files" / "app").write_text("corrupted", encoding="utf-8")
        commands, files = mock.Mock(), mock.Mock()
        environment = LinuxSystemdSimulationEnvironment(commands, files, LinuxSystemdCommandBuilder())
        with self.assertRaisesRegex(ValueError, "checksum"):
            environment.deploy(artifact)
        commands.run.assert_not_called()
        files.push.assert_not_called()

    def test_remote_directory_destinations_are_posix_even_on_windows(self):
        artifact = snapshot(self.root / "bundle", "A", {"app": "binary"})
        record = deployment_record(artifact.bundle_path, [{"src": "files", "dest": "/opt/app"}], lambda value: value)
        self.assertEqual(["/opt/app/app"], list(record["files"]))
        import shlex

        expression = shlex.split(remote_deployment_command(record))[-1]
        compile(expression, "remote-receipt", "exec")

    @unittest.skipIf(os.name == "nt", "Linux /proc executable attestation")
    def test_actual_process_script_is_recognized_and_unrelated_process_is_not(self):
        script = self.root / "runner.py"
        script.write_text("import time; time.sleep(60)", encoding="utf-8")
        process = subprocess.Popen([sys.executable, str(script)])
        try:
            record = {"entrypoint": str(script), "files": {str(script): identity.digest(script)}}
            self.assertTrue(identity.process_uses_artifact(record, process.pid))
            self.assertFalse(identity.process_uses_artifact({**record, "entrypoint": "another-script"}, process.pid))
            self.assertFalse(identity.process_uses_artifact(self.record, process.pid))
        finally:
            process.terminate()
            process.wait(timeout=5)


class LocalSimulationIdentityTest(unittest.TestCase):
    def test_relative_project_roots_keep_receipts_outside_deployment_tree(self):
        channel = mock.Mock()
        for environment in (
            WokwiSimulationEnvironment(Path("."), channel),
            MujocoSimulationEnvironment(Path("."), channel),
        ):
            with self.subTest(environment=type(environment).__name__):
                self.assertTrue(environment.identity.path.is_absolute())
                self.assertFalse(environment.identity.path.is_relative_to(Path.cwd()))

    def test_wokwi_redeploy_preserves_running_firmware_and_restart_selects_new_build(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory).resolve()
            contents = {"wokwi.toml": "[wokwi]\nfirmware='firmware.bin'\n", "diagram.json": "{}", "firmware.bin": "A"}
            first = snapshot(root / "A", "A", contents)
            second = snapshot(root / "B", "B", {**contents, "firmware.bin": "B"})
            live = set()
            processes = mock.Mock()
            processes.find_executable.return_value = "wokwi-cli"

            def start(argv, **_options):
                process = ManagedProcess(100 + processes.start.call_count, tuple(argv), 123)
                live.add(process.pid)
                return process

            processes.start.side_effect = start
            processes.owns.side_effect = lambda process: process.pid in live
            processes.terminate_group.side_effect = lambda process: live.discard(process.pid)
            environment = WokwiSimulationEnvironment(root / "project", processes)
            with mock.patch.dict(os.environ, {"GAR_WOKWI_FIRMWARE": "firmware.bin"}):
                environment.deploy(first)
                environment.start({})
                self.assertTrue(environment.observe({}, diagnostic=False)["app"]["build_id_match"])
                first_project = Path(processes.start.call_args.args[0][1])
                environment.deploy(second)
                environment.start({})
                self.assertEqual(1, processes.start.call_count)
                self.assertEqual("A", (first_project / "firmware.bin").read_text())
                result = environment.observe({}, diagnostic=False)["app"]
                self.assertEqual("A", result["running_build_id"])
                self.assertEqual("mismatch", result["build_id_verification"])
                environment.stop({})
                self.assertIsNone(environment.observe({}, diagnostic=False)["app"]["running_build_id"])
                environment.start({})
                self.assertEqual("B", environment.observe({}, diagnostic=False)["app"]["running_build_id"])

    def test_mujoco_certifies_only_the_deployed_model_and_keeps_health_separate(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory).resolve()
            artifact = snapshot(root / "bundle", "model-A", {"model.xml": "<mujoco/>"})
            channel = mock.Mock()
            channel.start.side_effect = lambda argv, **kw: ManagedProcess(22, tuple(argv), 55)
            channel.owns.return_value = True
            environment = MujocoSimulationEnvironment(root / "project", channel)
            with (
                mock.patch.object(environment, "_validate_model_or_raise"),
                mock.patch.object(environment, "_validate_model", return_value=(True, None)),
                mock.patch.dict(os.environ, {"GAR_MUJOCO_MODEL": str(root / "project" / "model.xml")}),
                mock.patch("scripts.gar_lib.simulation.runtime.mujoco.bridge_state", return_value=None),
            ):
                environment.deploy(artifact)
                environment.start({})
                result = environment.observe({}, diagnostic=True)
                self.assertTrue(result["app"]["build_id_match"])
                self.assertFalse(result["runtime"]["ok"])
                self.assertNotEqual(str(root / "project" / "model.xml"), channel.start.call_args.args[0][3])

    def test_latest_snapshot_is_expected_even_when_a_different_build_is_deployed(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = snapshot(Path(directory) / "bundle", "B", {"app": "binary"})
            store = mock.Mock()
            store.latest.return_value = artifact
            backend = mock.Mock()
            backend.observe.return_value = {
                "connection": {"state": "not_applicable", "ok": None},
                "runtime": {"state": "running", "ok": True},
                "app": {"state": "running", "ok": True, "running_build_id": "A", "deployed_build_id": "A"},
            }
            with mock.patch("scripts.gar_lib.simulation.observation.simulation_environment_for", return_value=backend):
                report = observe_simulation(artifact.workspace, {}, diagnostic=True, artifacts=store)
            self.assertFalse(report.ok)
            self.assertEqual("B", report.components["app"]["expected_build_id"])
            self.assertEqual("A", report.components["app"]["deployed_build_id"])
