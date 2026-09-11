from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support.filesystem import symlink_or_skip

from scripts.gar_lib.api import Gar
from scripts.gar_lib.artifacts.provenance import TargetToolsProvenance
from scripts.gar_lib.artifacts.store import LocalArtifactStore
from scripts.gar_lib.build.environment import build_environment_for
from scripts.gar_lib.cli import main
from scripts.gar_lib.commands.setup import configure_target_connection
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.errors import AccessConnectionError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.target.composition import _selected_target_manifest, target_environment_for
from scripts.gar_lib.target.esp32 import Esp32TargetEnvironment
from scripts.gar_lib.target.file_transfer import FileTransferTargetEnvironment
from scripts.gar_lib.target.manifest import TargetManifest


def workspace(root: Path, *, target: str = "adb_usb") -> Workspace:
    return Workspace(
        id="ws_target",
        name="Local/Product",
        branch="Product",
        connection={"type": "local", "path": str(root)},
        selected_environments={"codespace": "local", "target": target},
    )


class GarTargetArchitectureTest(unittest.TestCase):
    def test_target_manifest_prefers_the_local_product_tools_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            product_root = Path(tmp).resolve() / "product"
            tools_root = product_root / "sources" / "gar-tools"
            (tools_root / "targets").mkdir(parents=True)
            selected_workspace = Workspace(
                id="ws",
                name="Local/Product",
                branch="Product",
                connection={"type": "local", "path": str(product_root)},
                selected_target="raspberry-pi-5",
            )
            expected = mock.Mock()

            with (
                mock.patch(
                    "scripts.gar_lib.target.composition.discover_target_manifests",
                    return_value=[expected],
                ) as discover,
                mock.patch(
                    "scripts.gar_lib.target.composition.target_by_id",
                    return_value=expected,
                ),
            ):
                manifest = _selected_target_manifest(selected_workspace)

        self.assertIs(expected, manifest)
        discover.assert_called_once_with(tools_root=tools_root)

    def test_target_configure_has_no_artifact_dependency_and_reports_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "demo.env"
            source.write_text("PORT=5000\n", encoding="utf-8")
            selected_workspace = workspace(Path(tmp), target="ssh_scp")
            selected_workspace = Workspace(
                id=selected_workspace.id,
                name=selected_workspace.name,
                branch=selected_workspace.branch,
                connection=selected_workspace.connection,
                selected_environments=selected_workspace.selected_environments,
                selected_target="raspberry-pi-5",
            )
            environment = FileTransferTargetEnvironment(
                mock.Mock(host="raspi5"), mock.Mock(), privileged_install=True, prepare_recipe=Path("/recipe")
            )
            report_output = io.StringIO()
            diagnostics = io.StringIO()
            with (
                mock.patch("scripts.gar_lib.commands.target.resolve_workspace", return_value=selected_workspace),
                mock.patch("scripts.gar_lib.api.target_environment_for", return_value=environment),
                mock.patch.object(environment, "_install_privileged") as install,
                contextlib.redirect_stdout(report_output),
                contextlib.redirect_stderr(diagnostics),
            ):
                result = main(
                    [
                        "target",
                        "configure",
                        "--workspace",
                        "Local/Product",
                        "--app",
                        "demo",
                        "--file",
                        str(source),
                        "--json",
                    ]
                )

        payload = json.loads(report_output.getvalue())
        self.assertEqual(0, result)
        self.assertTrue(payload["ok"])
        self.assertEqual("demo", payload["app"])
        self.assertEqual("/etc/gar/demo.env", payload["destination"])
        self.assertTrue(payload["configured"])
        self.assertEqual("", diagnostics.getvalue())
        install.assert_called_once_with(source, "/etc/gar/demo.env", "0644")

    def test_target_configure_rejects_missing_or_symlink_source_before_target_access(self) -> None:
        selected_workspace = workspace(Path("/tmp/product"), target="ssh_scp")
        with (
            mock.patch("scripts.gar_lib.commands.target.resolve_workspace", return_value=selected_workspace),
            mock.patch("scripts.gar_lib.api.target_environment_for") as environment_for,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            result = main(
                ["target", "configure", "--workspace", "Local/Product", "--app", "demo", "--file", "/missing/demo.env"]
            )

        self.assertEqual(1, result)
        environment_for.assert_not_called()

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.env"
            source.write_text("PORT=5000\n", encoding="utf-8")
            link = Path(tmp) / "linked.env"
            symlink_or_skip(link, source)
            with (
                mock.patch("scripts.gar_lib.commands.target.resolve_workspace", return_value=selected_workspace),
                mock.patch("scripts.gar_lib.api.target_environment_for") as environment_for,
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                result = main(
                    ["target", "configure", "--workspace", "Local/Product", "--app", "demo", "--file", str(link)]
                )

        self.assertEqual(1, result)
        environment_for.assert_not_called()

    def test_target_configure_rejects_non_recipe_target_as_machine_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "demo.env"
            source.write_text("PORT=5000\n", encoding="utf-8")
            selected_workspace = workspace(Path(tmp), target="esp32_esptool")
            output = io.StringIO()
            diagnostics = io.StringIO()
            with (
                mock.patch("scripts.gar_lib.commands.target.resolve_workspace", return_value=selected_workspace),
                mock.patch("scripts.gar_lib.api.target_environment_for", return_value=Esp32TargetEnvironment("COM4")),
                contextlib.redirect_stdout(output),
                contextlib.redirect_stderr(diagnostics),
            ):
                result = main(
                    [
                        "target",
                        "configure",
                        "--workspace",
                        "Local/Product",
                        "--app",
                        "demo",
                        "--file",
                        str(source),
                        "--json",
                    ]
                )

        payload = json.loads(output.getvalue())
        self.assertEqual(1, result)
        self.assertFalse(payload["ok"])
        self.assertEqual("demo", payload["app"])
        self.assertFalse(payload["configured"])
        self.assertEqual("", diagnostics.getvalue())

    def test_file_target_configure_uses_sudo_installer_or_root_installer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "demo.env"
            source.write_text("PORT=5000\n", encoding="utf-8")
            channel = mock.Mock(host="raspi5")
            channel.run.return_value = subprocess.CompletedProcess([], 0, "1000\n", "")
            files = mock.Mock()
            files.push.return_value = subprocess.CompletedProcess([], 0, "", "")
            environment = FileTransferTargetEnvironment(
                channel, files, privileged_install=True, prepare_recipe=Path("/recipe")
            )
            environment.configure("demo", source)

        commands = [call.args[0] for call in channel.run.call_args_list]
        self.assertTrue(
            any(command.startswith("sudo -n /usr/local/lib/gar/gar-target-install install") for command in commands)
        )
        self.assertTrue(any(" 0644" in command for command in commands))

        root_channel = mock.Mock(host="luckfox")
        root_channel.run.side_effect = lambda command: subprocess.CompletedProcess(
            [], 0, "0\n" if command == "id -u" else "", ""
        )
        root_files = mock.Mock()
        root_files.push.return_value = subprocess.CompletedProcess([], 0, "", "")
        root_environment = FileTransferTargetEnvironment(
            root_channel, root_files, privileged_install=True, prepare_recipe=Path("/recipe")
        )
        with tempfile.TemporaryDirectory() as tmp:
            root_source = Path(tmp) / "demo.env"
            root_source.write_text("PORT=5000\n", encoding="utf-8")
            root_environment.configure("demo", root_source)

        root_commands = [call.args[0] for call in root_channel.run.call_args_list]
        self.assertTrue(
            any(command.startswith("/usr/local/lib/gar/gar-target-install install") for command in root_commands)
        )
        self.assertFalse(any(command.startswith("sudo -n ") for command in root_commands))

    def test_setup_saves_ssh_target_host_per_workspace(self) -> None:
        config = {"selected_environments": {"target": "ssh_scp"}}
        with (
            mock.patch(
                "scripts.gar_lib.commands.setup.target_setup.sys.stdin.isatty",
                return_value=True,
            ),
            mock.patch(
                "scripts.gar_lib.commands.setup.target_setup.safe_input",
                return_value="raspi-target",
            ),
            mock.patch("scripts.gar_lib.commands.setup.target_setup.save_config") as save,
        ):
            configure_target_connection(config)

        self.assertEqual("raspi-target", config["target"]["host"])
        save.assert_called_once_with(config)

    def test_legacy_native_target_build_runs_product_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            hook = root / "scripts" / "product-target-build.sh"
            hook.parent.mkdir()
            hook.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            artifact_root = root / "artifacts" / "from-codespace"
            artifact_file = artifact_root / "files" / "app"
            artifact_file.parent.mkdir(parents=True)
            artifact_file.write_text("app", encoding="utf-8")
            (artifact_root / "artifact.json").write_text(
                json.dumps({"deploy": {"app": {"files": [{"src": "files/app", "dest": "~/app"}]}}}),
                encoding="utf-8",
            )
            completed = mock.Mock(returncode=0)
            with mock.patch("scripts.gar_lib.build.local.subprocess.run", return_value=completed) as run:
                selected_workspace = Workspace(
                    id="ws_target",
                    name="Local/Product",
                    branch="Product",
                    connection={"type": "local", "path": str(root)},
                    selected_environments={"codespace": "native", "target": "esp32_esptool"},
                )
                artifact = build_environment_for(
                    selected_workspace,
                    LocalArtifactStore(),
                ).build(
                    ArtifactKind.TARGET_APP,
                    selected_workspace,
                )

        self.assertEqual(ArtifactKind.TARGET_APP, artifact.kind)
        run.assert_called_once_with([str(hook)], cwd=root, check=False, env=mock.ANY)

    def test_target_build_uses_the_workspace_build_environment(self) -> None:
        selected_workspace = workspace(Path("/tmp/product"))
        build_environment = mock.Mock()
        artifact = mock.Mock(bundle_path="/tmp/bundle")
        build_environment.build.return_value = artifact

        with (
            mock.patch(
                "scripts.gar_lib.api.build_environment_for",
                return_value=build_environment,
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = Gar(selected_workspace).target.build()

        self.assertIs(artifact, result)
        build_environment.build.assert_called_once_with(ArtifactKind.TARGET_APP, selected_workspace)

    def test_target_deploy_uses_latest_artifact_and_environment(self) -> None:
        selected_workspace = workspace(Path("/tmp/product"))
        artifact = mock.Mock(bundle_path="/tmp/bundle")
        artifacts = mock.Mock()
        artifacts.latest.return_value = artifact
        environment = mock.Mock()

        with (
            mock.patch(
                "scripts.gar_lib.api.target_environment_for",
                return_value=environment,
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = Gar(selected_workspace, artifacts).target.deploy()

        self.assertIs(artifact, result)
        artifacts.latest.assert_called_once_with(ArtifactKind.TARGET_APP, selected_workspace)
        environment.deploy.assert_called_once_with(artifact)

    def test_target_adb_failure_uses_shared_recovery_guidance(self) -> None:
        selected_workspace = workspace(Path("/tmp/product"))
        environment = mock.Mock()
        environment.deploy.side_effect = AccessConnectionError(
            channel="adb",
            endpoint="device-1",
            reason="no_device",
            returncode=1,
        )
        artifacts = mock.Mock()
        artifacts.latest.return_value = mock.Mock(bundle_path="/tmp/bundle")
        stderr = io.StringIO()
        with (
            mock.patch("scripts.gar_lib.commands.target.resolve_workspace", return_value=selected_workspace),
            mock.patch("scripts.gar_lib.api.LocalArtifactStore", return_value=artifacts),
            mock.patch(
                "scripts.gar_lib.api.target_environment_for",
                return_value=environment,
            ),
            mock.patch("scripts.gar_lib.commands.target.run_terminal_run_command") as terminal_request,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(stderr),
        ):
            result = main(["target", "deploy", "--workspace", "Local/Product"])

        self.assertEqual(1, result)
        terminal_request.assert_not_called()
        self.assertIn("gar usb attach", stderr.getvalue())

    def test_file_target_transfers_manifest_and_applies_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source = root / "files" / "app"
            source.parent.mkdir()
            source.write_text("app", encoding="utf-8")
            (root / "artifact.json").write_text(
                json.dumps({"deploy": {"app": {"files": [{"src": "files/app", "dest": "bin/app", "mode": "0755"}]}}}),
                encoding="utf-8",
            )
            selected_workspace = workspace(root)
            artifact = Artifact(ArtifactKind.TARGET_APP, selected_workspace, root)
            command_channel = mock.Mock()
            command_channel.run.return_value.returncode = 0
            file_channel = mock.Mock()
            file_channel.push.return_value.returncode = 0
            environment = FileTransferTargetEnvironment(
                command_channel,
                file_channel,
                base_destination="/opt/product",
            )

            environment.deploy(artifact)

        file_channel.push.assert_called_once_with(source, "/opt/product/bin/app")
        self.assertEqual(
            [mock.call("mkdir -p /opt/product/bin"), mock.call("chmod 0755 /opt/product/bin/app")],
            command_channel.run.call_args_list,
        )

    def test_ssh_file_target_stages_and_uses_limited_installer_for_system_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source = root / "files" / "app"
            source.parent.mkdir()
            source.write_text("app", encoding="utf-8")
            (root / "artifact.json").write_text(
                json.dumps(
                    {"deploy": {"app": {"files": [{"src": "files/app", "dest": "/opt/gar/apps/demo", "mode": "0755"}]}}}
                ),
                encoding="utf-8",
            )
            artifact = Artifact(ArtifactKind.TARGET_APP, workspace(root), root)
            command_channel = mock.Mock(host="raspi5")
            command_channel.run.return_value.returncode = 0
            command_channel.run.return_value.stderr = ""
            file_channel = mock.Mock()
            file_channel.push.return_value.returncode = 0
            file_channel.push.return_value.stderr = ""
            environment = FileTransferTargetEnvironment(
                command_channel,
                file_channel,
                privileged_install=True,
            )

            environment.deploy(artifact)

        self.assertEqual(source, file_channel.push.call_args.args[0])
        self.assertIn("/tmp/gar-stage-", file_channel.push.call_args.args[1])
        commands = [call.args[0] for call in command_channel.run.call_args_list]
        self.assertTrue(any("gar-target-install install" in command for command in commands))
        self.assertTrue(any("gar-target-install enable-app demo" in command for command in commands))
        self.assertFalse(any(command.startswith("sudo -n cp") for command in commands))

    def test_root_ssh_target_invokes_limited_installer_without_sudo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "files" / "app"
            source.parent.mkdir()
            source.write_text("app", encoding="utf-8")
            (root / "artifact.json").write_text(
                json.dumps({"deploy": {"app": {"files": [{"src": "files/app", "dest": "/opt/gar/apps/demo"}]}}}),
                encoding="utf-8",
            )
            artifact = Artifact(ArtifactKind.TARGET_APP, workspace(root), root)
            command_channel = mock.Mock(host="luckfox-lyra")

            def run(command: str):
                if command == "id -u":
                    return subprocess.CompletedProcess([], 0, "0\n", "")
                return subprocess.CompletedProcess([], 0, "", "")

            command_channel.run.side_effect = run
            file_channel = mock.Mock()
            file_channel.push.return_value = subprocess.CompletedProcess([], 0, "", "")
            environment = FileTransferTargetEnvironment(
                command_channel,
                file_channel,
                privileged_install=True,
            )

            environment.deploy(artifact)

        commands = [call.args[0] for call in command_channel.run.call_args_list]
        installer_commands = [command for command in commands if "gar-target-install" in command]
        self.assertEqual(2, len(installer_commands))
        self.assertTrue(
            all(command.startswith("/usr/local/lib/gar/gar-target-install") for command in installer_commands)
        )
        self.assertFalse(any("sudo" in command for command in installer_commands))

    def test_target_resolver_composes_adb_channels(self) -> None:
        selected_workspace = Workspace(
            id="ws",
            name="Local/Product",
            branch="Product",
            connection={"type": "local", "path": "/tmp/product"},
            selected_environments={"target": "adb_usb"},
            target={"serial": "device-1", "dest": "/data/local/tmp"},
        )
        environment = target_environment_for(selected_workspace)

        completed = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch("scripts.gar_lib.access.adb.subprocess.run", return_value=completed) as run:
            artifact = mock.Mock(kind=ArtifactKind.TARGET_APP)
            with (
                mock.patch(
                    "scripts.gar_lib.target.file_transfer.load_deploy_files",
                    return_value=(Path("/tmp"), [{"src": "app", "dest": "app"}]),
                ),
                mock.patch(
                    "scripts.gar_lib.target.file_transfer.resolve_artifact_src",
                    return_value=Path("/tmp/app"),
                ),
            ):
                environment.deploy(artifact)

        self.assertEqual(
            ("adb", "-s", "device-1", "push", str(Path("/tmp/app")), "/data/local/tmp/app"),
            run.call_args_list[-1].args[0],
        )

    def test_target_resolver_uses_configured_ssh_host(self) -> None:
        selected_workspace = Workspace(
            id="ws",
            name="Local/Product",
            branch="Product",
            connection={"type": "local", "path": "/tmp/product"},
            selected_environments={"target": "ssh_scp"},
            target={"host": "raspi", "dest": "/opt/product"},
        )
        environment = target_environment_for(selected_workspace)

        self.assertEqual("raspi", environment.command_channel.host)
        self.assertEqual("raspi", environment.file_channel.host)
        self.assertEqual("/opt/product", environment.base_destination)

    def test_target_resolver_uses_selected_target_provisioning_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_dir = Path(tmp) / "targets" / "raspberry-pi-5"
            recipe = target_dir / "provisioning" / "raspberry-pi-os-systemd"
            recipe.mkdir(parents=True)
            manifest_path = target_dir / "target.json"
            manifest_path.write_text("{}\n", encoding="utf-8")
            manifest = TargetManifest(
                id="raspberry-pi-5",
                display_name="Raspberry Pi 5",
                description="test",
                tools_root="targets/raspberry-pi-5",
                default_backends={"target": "ssh_scp"},
                backend_notes={},
                provisioning={
                    "ssh_scp": {
                        "type": "ssh-script",
                        "path": "provisioning/raspberry-pi-os-systemd",
                    }
                },
                source_path=manifest_path,
            )
            selected_workspace = Workspace(
                id="ws",
                name="Local/Product",
                branch="Product",
                connection={"type": "local", "path": "/tmp/product"},
                selected_target="raspberry-pi-5",
                selected_environments={"target": "ssh_scp"},
                target={"host": "raspi5"},
            )
            active_tools = TargetToolsProvenance(
                target_id="raspberry-pi-5",
                gar_tools_commit="c" * 40,
                target_recipe_version="1",
            )
            with (
                mock.patch(
                    "scripts.gar_lib.target.composition.discover_target_manifests",
                    return_value=[manifest],
                ),
                mock.patch(
                    "scripts.gar_lib.target.composition.collect_target_tools_provenance",
                    return_value=active_tools,
                ) as collect_provenance,
            ):
                environment = target_environment_for(selected_workspace)

        self.assertTrue(environment.privileged_install)
        self.assertEqual(recipe.resolve(), environment.prepare_recipe)
        self.assertIs(active_tools, environment.active_tools_provenance)
        self.assertTrue(environment.require_active_tools_provenance)
        collect_provenance.assert_called_once_with(
            manifest_path,
            "ssh_scp",
            target_id="raspberry-pi-5",
        )

    def test_target_backend_builds_esp32_environment(self) -> None:
        selected_workspace = Workspace(
            id="ws",
            name="Local/Product",
            branch="Product",
            connection={"type": "local", "path": "/tmp/product"},
            selected_environments={"target": "esp32_esptool"},
            esp32={"port": "COM4"},
        )

        environment = target_environment_for(selected_workspace)

        self.assertIsInstance(environment, Esp32TargetEnvironment)
        self.assertEqual("COM4", environment.port)

    def test_esp32_environment_resolves_firmware_directory_from_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            firmware = root / "files" / "firmware"
            firmware.mkdir(parents=True)
            for name in ("bootloader.bin", "partitions.bin", "boot_app0.bin", "firmware.bin"):
                (firmware / name).write_bytes(b"firmware")
            (root / "artifact.json").write_text(
                json.dumps({"deploy": {"app": {"files": [{"src": "files/firmware", "dest": "firmware"}]}}}),
                encoding="utf-8",
            )
            selected_workspace = workspace(root, target="esp32_esptool")
            artifact = Artifact(ArtifactKind.TARGET_APP, selected_workspace, root)
            with mock.patch(
                "scripts.gar_lib.target.esp32.run_esp32_flash_command",
                return_value=0,
            ) as flash:
                Esp32TargetEnvironment("COM4").deploy(artifact)

        flash.assert_called_once_with(artifact_dir=str(firmware), port="COM4")


if __name__ == "__main__":
    unittest.main()
