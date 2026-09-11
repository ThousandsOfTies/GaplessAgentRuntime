from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.gar_lib.access.channel import AccessResult
from scripts.gar_lib.access.uuu import LocalUuuCommandChannel
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.target.manifest import TargetManifest
from scripts.gar_lib.target.uuu import UuuTargetEnvironment


def _artifact(root: Path) -> Artifact:
    (root / "images").mkdir()
    (root / "images" / "image.wic.zst").write_bytes(b"image")
    (root / "artifact.json").write_text(
        '{"name":"demo","deploy":{"image":{"files":[{"src":"images/image.wic.zst","dest":"image.wic.zst"}]}}}',
        encoding="utf-8",
    )
    workspace = Workspace(
        id="ws",
        name="Local/Product",
        branch="Product",
        connection={"type": "local", "path": str(root)},
    )
    return Artifact(ArtifactKind.TARGET_APP, workspace, root)


class UuuTargetEnvironmentTests(unittest.TestCase):
    def test_local_channel_reports_missing_windows_or_posix_executable(self) -> None:
        with mock.patch(
            "scripts.gar_lib.access.uuu.subprocess.run",
            side_effect=FileNotFoundError("not found"),
        ):
            with self.assertRaisesRegex(GarDomainError, "UUU commandを起動できません"):
                LocalUuuCommandChannel().run(("uuu", "-h"), cwd=Path("."))

    def test_deploy_expands_configured_image_command_without_a_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            artifact = _artifact(root)
            manifest = TargetManifest(
                id="frdm-imx91s",
                display_name="FRDM-IMX91S",
                description="",
                tools_root="targets/frdm-imx91s",
                default_backends={"target": "uuu"},
                backend_notes={},
                provisioning={
                    "uuu": {
                        "type": "uuu",
                        "command": ["uuu", "-b", "sd_all", "{image}"],
                        "imageSection": "image",
                    }
                },
            )
            command_channel = mock.Mock()
            command_channel.run.return_value = AccessResult(("uuu",), 0)
            environment = UuuTargetEnvironment(manifest, command_channel=command_channel)
            environment.deploy(artifact)

        command_channel.run.assert_called_once_with(
            ["uuu", "-b", "sd_all", str(root / "images" / "image.wic.zst")],
            cwd=root / "images",
        )

    def test_serial_verification_uses_workspace_console_port_after_flash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = _artifact(root)
            manifest = TargetManifest(
                id="frdm-imx91s",
                display_name="FRDM-IMX91S",
                description="",
                tools_root="targets/frdm-imx91s",
                default_backends={"target": "uuu"},
                backend_notes={},
                provisioning={
                    "uuu": {
                        "type": "uuu",
                        "command": ["uuu", "{image}"],
                        "imageSection": "image",
                        "serialVerify": {"pattern": "login:", "baud": 115200, "timeoutSeconds": 5},
                    }
                },
            )
            command_channel = mock.Mock()
            command_channel.run.return_value = AccessResult(("uuu",), 0)
            serial_verifier = mock.Mock()
            environment = UuuTargetEnvironment(
                manifest,
                console_port="COM5",
                command_channel=command_channel,
                serial_verifier=serial_verifier,
            )
            environment.deploy(artifact)

        serial_verifier.wait.assert_called_once_with(
            "COM5",
            baud=115200,
            pattern="login:",
            timeout_seconds=5.0,
        )
