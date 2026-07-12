from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.gar_lib.access.base import CommandResult, TransferResult
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.simulation.linux_systemd import LinuxSystemdSimulationEnvironment


class GarLinuxSystemdEnvironmentTest(unittest.TestCase):
    def test_deploy_uses_injected_channels_without_knowing_ssh_or_adb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "files" / "app"
            source.parent.mkdir()
            source.write_text("app", encoding="utf-8")
            (root / "artifact.json").write_text(
                json.dumps(
                    {
                        "deploy": {
                            "app": {
                                "files": [
                                    {"src": "files/app", "dest": "~/app", "mode": "0755"}
                                ]
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            workspace = Workspace("ws", "Local/App", "App", {"type": "local", "path": tmp})
            artifact = Artifact(ArtifactKind.SIM_APP, workspace, root)
            commands = mock.Mock()
            commands.run.return_value = CommandResult(("channel",), 0)
            files = mock.Mock()
            files.push.return_value = TransferResult(("channel",), 0)

            LinuxSystemdSimulationEnvironment(commands, files).deploy(artifact)

        files.push.assert_called_once()
        install = commands.run.call_args.args[0]
        self.assertIn('mkdir -p $(dirname "${HOME}"/', install)
        self.assertNotIn("sudo", install)
        self.assertIn("chmod 0755", install)

    def test_runtime_artifact_maps_system_destinations(self) -> None:
        command = LinuxSystemdSimulationEnvironment._install_command(
            "/tmp/cuse_i2c",
            "/usr/local/sbin/cuse_i2c",
            source_is_dir=False,
            mode="0755",
        )

        self.assertIn("sudo cp", command)
        self.assertIn("/usr/local/sbin/cuse_i2c", command)
