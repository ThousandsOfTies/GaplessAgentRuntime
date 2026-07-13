from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.gar_lib.access.process import ProcessLaunchResult
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.simulation.host_resolver import ConfigSimulationHostControllerResolver
from scripts.gar_lib.simulation.resolver import ConfigSimulationEnvironmentResolver
from scripts.gar_lib.simulation.wokwi_environment import WokwiSimulationEnvironment


class GarWokwiEnvironmentTest(unittest.TestCase):
    def _workspace(self, root: Path) -> Workspace:
        return Workspace(
            id="ws-wokwi",
            name="Local/WokwiProduct",
            branch="WokwiProduct",
            connection={"type": "local", "path": str(root)},
            selected_environments={"simulator": "wokwi"},
        )

    def _project(self, root: Path) -> Path:
        project = root / ".gar" / "wokwi" / "m5stackc"
        firmware = project / ".pio" / "build" / "m5stackc" / "firmware.bin"
        firmware.parent.mkdir(parents=True)
        firmware.write_bytes(b"firmware")
        firmware.with_name("firmware.elf").write_bytes(b"elf")
        (project / "diagram.json").write_text("{}", encoding="utf-8")
        (project / "wokwi.toml").write_text(
            "[wokwi]\nfirmware = '.pio/build/m5stackc/firmware.bin'\n",
            encoding="utf-8",
        )
        return project

    def test_resolver_selects_local_wokwi_without_simulation_host(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            environment = ConfigSimulationEnvironmentResolver().for_workspace(self._workspace(root))

            self.assertIsInstance(environment, WokwiSimulationEnvironment)
            self.assertIsNone(environment.runtime_host)
            self.assertEqual(root / ".gar" / "wokwi" / "m5stackc", environment.project_dir)

    def test_wokwi_does_not_resolve_an_ec2_host_controller(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self._workspace(Path(tmp))

            with self.assertRaisesRegex(GarDomainError, "instance_id, region"):
                ConfigSimulationHostControllerResolver().for_workspace(workspace)

    def test_start_launches_local_wokwi_cli_and_records_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp))
            processes = mock.Mock()
            processes.find_executable.return_value = "/home/user/bin/wokwi-cli"
            processes.is_running.return_value = False
            processes.start.return_value = ProcessLaunchResult(1234, ("wokwi-cli",))
            environment = WokwiSimulationEnvironment(project, processes)

            with contextlib.redirect_stdout(io.StringIO()):
                result = environment.start({})

            self.assertEqual(0, result)
            argv = processes.start.call_args.args[0]
            self.assertEqual("/home/user/bin/wokwi-cli", argv[0])
            self.assertIn(str(project), argv)
            self.assertIn("--serial-log-file", argv)
            state = json.loads((project / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(1234, state["pid"])
            self.assertEqual("wokwi", state["environment"])

    def test_stop_terminates_only_the_recorded_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp))
            (project / "state.json").write_text('{"pid": 1234}\n', encoding="utf-8")
            processes = mock.Mock()
            processes.is_running.return_value = True
            environment = WokwiSimulationEnvironment(project, processes)

            with contextlib.redirect_stdout(io.StringIO()):
                result = environment.stop({})

            self.assertEqual(0, result)
            processes.terminate_group.assert_called_once_with(1234)
            state = json.loads((project / "state.json").read_text(encoding="utf-8"))
            self.assertEqual("stopped", state["status"])

    def test_diag_returns_wokwi_specific_structured_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp))
            processes = mock.Mock()
            processes.find_executable.return_value = "/home/user/bin/wokwi-cli"
            environment = WokwiSimulationEnvironment(project, processes)

            report = environment.diag({})
            payload = report.to_payload(host="ignored-ec2-host")

            self.assertEqual(0, report.exit_code)
            self.assertEqual("wokwi", payload["environment"])
            self.assertTrue(payload["files"]["firmware"])
            self.assertNotIn("host", payload)
            self.assertNotIn("processes", payload)

    def test_deploy_copies_manifest_files_to_project_relative_destinations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "bundle"
            source = bundle / "files" / "firmware.bin"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"firmware")
            (bundle / "artifact.json").write_text(
                json.dumps(
                    {
                        "deploy": {
                            "app": {
                                "files": [
                                    {
                                        "src": "files/firmware.bin",
                                        "dest": ".pio/build/m5stackc/firmware.bin",
                                    }
                                ]
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            workspace = self._workspace(root)
            project = root / "project"
            environment = WokwiSimulationEnvironment(project, mock.Mock())

            environment.deploy(Artifact(ArtifactKind.SIM_APP, workspace, bundle))

            self.assertEqual(
                b"firmware",
                (project / ".pio" / "build" / "m5stackc" / "firmware.bin").read_bytes(),
            )

    def test_deploy_rejects_a_separate_runtime_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            environment = WokwiSimulationEnvironment(root / "project", mock.Mock())
            artifact = Artifact(ArtifactKind.SIM_RUNTIME, self._workspace(root), root)

            with self.assertRaisesRegex(GarDomainError, "不要"):
                environment.deploy(artifact)
