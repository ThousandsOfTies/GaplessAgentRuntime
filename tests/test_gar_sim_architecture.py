from __future__ import annotations

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.gar_lib.api import Gar, SimulationRuntime, _workspace_hardware
from scripts.gar_lib.artifacts.store import LocalArtifactStore
from scripts.gar_lib.build.codespaces import CodespacesBuildEnvironment
from scripts.gar_lib.build.docker import DockerBuildEnvironment
from scripts.gar_lib.build.environment import build_environment_for
from scripts.gar_lib.build.local import LocalBuildEnvironment
from scripts.gar_lib.commands.workspace_resolver import resolve_workspace
from scripts.gar_lib.core.artifact import ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace


def local_workspace(root: Path, *, simulator: str = "local_docker") -> Workspace:
    return Workspace(
        id="ws_test",
        name="Local/Product",
        branch="Product",
        connection={"type": "local", "path": str(root)},
        selected_environments={"codespace": "local", "simulator": simulator},
    )


def cli_args(**values: object) -> argparse.Namespace:
    return argparse.Namespace(**{"json_output": False, **values})


class GarSimulationArchitectureTest(unittest.TestCase):
    def test_sim_deploy_rejects_artifact_built_for_previous_host_provider(self) -> None:
        workspace = Workspace(
            id="ws_test",
            name="Local/Product",
            branch="Product",
            connection={"type": "local", "path": "/tmp/product"},
            selected_environments={
                "codespace": "local",
                "simulator": "ssh_remote",
                "simulation_host": "virtualbox",
            },
            simulation_host={"provider": "virtualbox", "host": "gar-sim-local"},
            virtualbox={"vm": "GAR Ubuntu Sim"},
        )
        artifact = mock.Mock(bundle_path=Path("/tmp/artifact"))
        artifacts = mock.Mock()
        artifacts.latest.return_value = artifact
        metadata = mock.Mock()
        metadata.target.architecture = "aarch64"

        with mock.patch("scripts.gar_lib.api.load_artifact_metadata", return_value=metadata):
            with self.assertRaisesRegex(GarDomainError, "aarch64 != x86_64"):
                Gar(workspace, artifacts).sim.app.deploy()

    def test_unresolved_workspace_hardware_never_uses_the_current_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd_hardware = Path(tmp) / "hardware"
            cwd_hardware.mkdir()
            (cwd_hardware / "gpio.csv").write_text(
                "name,chip,line,direction,role,active,initial,pull,sim_control,description\n"
                "foreign,/dev/gpiochip0,1,input,button,high,,,,foreign product\n",
                encoding="utf-8",
            )
            remote_workspace = Workspace(
                id="ws_remote",
                name="Codespaces/Product",
                branch="Product",
                connection={"type": "codespaces", "codespace": "product-space"},
            )

            with mock.patch("scripts.gar_lib.core.hardware.Path.cwd", return_value=Path(tmp)):
                hardware = _workspace_hardware(remote_workspace)

        self.assertTrue(all(not rows for rows in hardware.values()))

    def test_runtime_configures_system_env_through_environment_capability(self) -> None:
        workspace = local_workspace(Path("/tmp/product"))
        environment = mock.Mock()
        environment.configure_system_env.return_value = "/etc/gar/system/demo.env"

        with mock.patch("scripts.gar_lib.api.simulation_environment_for", return_value=environment):
            destination = SimulationRuntime(workspace, mock.Mock()).configure_system_env("demo", {"A": "1"})

        self.assertEqual("/etc/gar/system/demo.env", destination)
        environment.configure_system_env.assert_called_once_with("demo", {"A": "1"})

    def test_runtime_rejects_system_env_for_unsupported_environment(self) -> None:
        workspace = local_workspace(Path("/tmp/product"))

        with mock.patch("scripts.gar_lib.api.simulation_environment_for", return_value=object()):
            with self.assertRaisesRegex(GarDomainError, "system-managed runtime env"):
                SimulationRuntime(workspace, mock.Mock()).configure_system_env("demo", {"A": "1"})

    def test_workspace_lookup_resolves_workspace_name(self) -> None:
        entry = {
            "id": "ws_test",
            "name": "Local/Product",
            "branch": "Product",
            "connection": {"type": "local", "path": "/tmp/product"},
            "selected_environments": {"codespace": "local"},
            "selected_target": "linux-device",
            "target": {"host": "raspi", "dest": "/opt/product"},
        }
        with (
            mock.patch("scripts.gar_lib.commands.workspace_resolver.load_config", return_value={"workspaces": [entry]}),
            mock.patch("scripts.gar_lib.commands.workspace_resolver.saved_workspaces", return_value=[entry]),
        ):
            workspace = resolve_workspace("Local/Product")

        self.assertEqual("ws_test", workspace.id)
        self.assertEqual("local", workspace.selected_environments["codespace"])
        self.assertEqual("linux-device", workspace.selected_target)
        self.assertEqual("raspi", workspace.target["host"])

    def test_workspace_lookup_prefers_product_hardware_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            product_root = Path(tmp).resolve() / "product"
            product_hardware = product_root / "hardware"
            product_hardware.mkdir(parents=True)
            bundled_hardware = product_root / "sources" / "gar-tools" / "targets" / "linux-device" / "hardware"
            bundled_hardware.mkdir(parents=True)
            entry = {
                "id": "ws_test",
                "name": "Local/Product",
                "branch": "Product",
                "connection": {"type": "local", "path": str(product_root)},
                "selected_target": "linux-device",
            }
            with (
                mock.patch(
                    "scripts.gar_lib.commands.workspace_resolver.load_config",
                    return_value={"workspaces": [entry]},
                ),
                mock.patch(
                    "scripts.gar_lib.commands.workspace_resolver.saved_workspaces",
                    return_value=[entry],
                ),
            ):
                workspace = resolve_workspace(None)

        self.assertEqual(product_hardware, workspace.hardware_dir)

    def test_workspace_lookup_does_not_use_target_pack_as_product_hardware(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            product_root = Path(tmp) / "GarVibeRemote"
            bundled_hardware = product_root / "sources" / "gar-tools" / "targets" / "linux-device" / "hardware"
            bundled_hardware.mkdir(parents=True)
            entry = {
                "id": "ws_vibe_remote",
                "name": "Local/GarVibeRemote",
                "branch": "GarVibeRemote",
                "connection": {"type": "local", "path": str(product_root)},
                "selected_target": "linux-device",
            }
            with (
                mock.patch(
                    "scripts.gar_lib.commands.workspace_resolver.load_config",
                    return_value={"workspaces": [entry]},
                ),
                mock.patch(
                    "scripts.gar_lib.commands.workspace_resolver.saved_workspaces",
                    return_value=[entry],
                ),
            ):
                workspace = resolve_workspace(None)

        self.assertIsNone(workspace.hardware_dir)

    def test_workspace_lookup_honours_explicit_hardware_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            product_root = Path(tmp).resolve() / "product"
            explicit_hardware = product_root / "config" / "hardware"
            entry = {
                "id": "ws_test",
                "name": "Local/Product",
                "branch": "Product",
                "connection": {"type": "local", "path": str(product_root)},
                "selected_target": "linux-device",
                "hardware": {"path": "config/hardware"},
            }
            with (
                mock.patch(
                    "scripts.gar_lib.commands.workspace_resolver.load_config",
                    return_value={"workspaces": [entry]},
                ),
                mock.patch(
                    "scripts.gar_lib.commands.workspace_resolver.saved_workspaces",
                    return_value=[entry],
                ),
            ):
                workspace = resolve_workspace(None)

        self.assertEqual(explicit_hardware, workspace.hardware_dir)

    def test_workspace_lookup_requires_selector_for_multiple_entries(self) -> None:
        entries = [
            {
                "id": f"ws_{index}",
                "name": f"Local/Product{index}",
                "branch": f"Product{index}",
                "connection": {"type": "local", "path": f"/tmp/product{index}"},
            }
            for index in (1, 2)
        ]
        with (
            mock.patch("scripts.gar_lib.commands.workspace_resolver.load_config", return_value={"workspaces": entries}),
            mock.patch("scripts.gar_lib.commands.workspace_resolver.saved_workspaces", return_value=entries),
        ):
            with self.assertRaises(GarDomainError):
                resolve_workspace(None)

    def test_local_build_environment_runs_product_hook_and_returns_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            hook = root / "scripts" / "product-sim-build.sh"
            hook.parent.mkdir()
            hook.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            artifact_root = root / "artifacts" / "from-codespace"
            artifact_file = artifact_root / "files" / "app"
            artifact_file.parent.mkdir(parents=True)
            artifact_file.write_text("app", encoding="utf-8")
            (artifact_root / "artifact.json").write_text(
                json.dumps(
                    {
                        "deploy": {
                            "app": {
                                "files": [{"src": "files/app", "dest": "~/app"}],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            workspace = local_workspace(root)
            completed = mock.Mock(returncode=0)
            with mock.patch("scripts.gar_lib.build.local.subprocess.run", return_value=completed) as run:
                artifact = LocalBuildEnvironment(LocalArtifactStore()).build(ArtifactKind.SIM_APP, workspace)

        self.assertEqual(ArtifactKind.SIM_APP, artifact.kind)
        run.assert_called_once_with([str(hook)], cwd=root, check=False, env=mock.ANY)

    def test_esp32_target_does_not_replace_docker_product_build_environment(self) -> None:
        workspace = Workspace(
            id="ws_esp32",
            name="Local/ESP32Product",
            branch="ESP32Product",
            connection={"type": "local", "path": "/tmp/product"},
            selected_environments={
                "codespace": "local",
                "simulator": "wokwi",
                "target": "esp32_esptool",
            },
            selected_target="esp32",
        )

        environment = build_environment_for(workspace, LocalArtifactStore())

        self.assertIsInstance(environment, DockerBuildEnvironment)

    def test_esp32_target_does_not_replace_codespaces_product_build_environment(self) -> None:
        workspace = Workspace(
            id="ws_esp32",
            name="Codespaces/ESP32Product",
            branch="ESP32Product",
            connection={
                "type": "codespaces",
                "path": "/workspaces/product",
                "codespace": "product-space",
            },
            selected_environments={
                "codespace": "github_codespaces",
                "simulator": "wokwi",
                "target": "esp32_esptool",
            },
            selected_target="esp32",
        )

        environment = build_environment_for(workspace, LocalArtifactStore())

        self.assertIsInstance(environment, CodespacesBuildEnvironment)

    def test_sim_app_build_uses_the_workspace_build_environment(self) -> None:
        workspace = local_workspace(Path("/tmp/product"))
        artifact = mock.Mock(bundle_path="/tmp/bundle")
        build_environment = mock.Mock()
        build_environment.build.return_value = artifact

        with (
            mock.patch(
                "scripts.gar_lib.api.build_environment_for",
                return_value=build_environment,
            ) as build_for,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = Gar(workspace).sim.app.build()

        self.assertIs(artifact, result)
        build_for.assert_called_once_with(workspace, mock.ANY)
        build_environment.build.assert_called_once_with(ArtifactKind.SIM_APP, workspace)

    def test_sim_app_clean_uses_the_workspace_build_environment(self) -> None:
        workspace = local_workspace(Path("/tmp/product"))
        build_environment = mock.Mock()

        with (
            mock.patch(
                "scripts.gar_lib.api.build_environment_for",
                return_value=build_environment,
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = Gar(workspace).sim.app.clean()

        self.assertIsNone(result)
        build_environment.clean.assert_called_once_with(ArtifactKind.SIM_APP, workspace)

    def test_codespaces_build_runs_hook_and_materializes_artifact(self) -> None:
        workspace = Workspace(
            id="ws_test",
            name="Codespaces/Product",
            branch="Product",
            connection={
                "type": "codespaces",
                "path": "/workspaces/product",
                "codespace": "product-space",
            },
            selected_environments={"codespace": "github_codespaces"},
        )
        artifact = mock.Mock()
        artifacts = mock.Mock(spec=LocalArtifactStore)
        artifacts.sync_from_codespaces.return_value = artifact
        completed = mock.Mock(returncode=0)

        with mock.patch("scripts.gar_lib.build.codespaces.subprocess.run", return_value=completed) as run:
            result = CodespacesBuildEnvironment(artifacts).build(ArtifactKind.SIM_APP, workspace)

        self.assertIs(artifact, result)
        run.assert_called_once_with(
            [
                "gh",
                "codespace",
                "ssh",
                "-c",
                "product-space",
                "--",
                "cd /workspaces/product && scripts/product-sim-build.sh",
            ],
            check=False,
        )
        artifacts.sync_from_codespaces.assert_called_once_with(ArtifactKind.SIM_APP, workspace)
        artifacts.latest.assert_not_called()

    def test_wokwi_runtime_build_does_not_invoke_a_product_runtime_hook(self) -> None:
        workspace = local_workspace(Path("/tmp/product"), simulator="wokwi")

        with (
            mock.patch(
                "scripts.gar_lib.api.simulation_environment_for",
                return_value=mock.Mock(requires_runtime_artifact=False),
            ),
            mock.patch("scripts.gar_lib.api.build_environment_for") as build_for,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = Gar(workspace).sim.runtime.build()

        self.assertIsNone(result)
        build_for.assert_not_called()

    def test_wokwi_runtime_deploy_does_not_require_an_artifact(self) -> None:
        workspace = local_workspace(Path("/tmp/product"), simulator="wokwi")
        environment = mock.Mock(requires_runtime_artifact=False)
        artifacts = mock.Mock()

        with (
            mock.patch(
                "scripts.gar_lib.api.simulation_environment_for",
                return_value=environment,
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = Gar(workspace, artifacts).sim.runtime.deploy()

        self.assertIsNone(result)
        artifacts.latest.assert_not_called()
        environment.deploy.assert_not_called()
