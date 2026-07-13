from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.gar_lib.artifacts.store import LocalArtifactStore
from scripts.gar_lib.build.codespaces import CodespacesBuildEnvironment
from scripts.gar_lib.build.local import LocalBuildEnvironment
from scripts.gar_lib.commands.sim_next import SimCommandServices, dispatch
from scripts.gar_lib.core.artifact import ArtifactKind
from scripts.gar_lib.core.command import SIM_BUILD, SIM_RUNTIME_BUILD, SIM_RUNTIME_DEPLOY
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.workspaces.registry import ConfigWorkspaceRegistry


def local_workspace(root: Path) -> Workspace:
    return Workspace(
        id="ws_test",
        name="Local/Product",
        branch="Product",
        connection={"type": "local", "path": str(root)},
        selected_environments={"codespace": "local"},
    )


class GarNextArchitectureTest(unittest.TestCase):
    def test_workspace_registry_resolves_workspace_name(self) -> None:
        entry = {
            "id": "ws_test",
            "name": "Local/Product",
            "branch": "Product",
            "connection": {"type": "local", "path": "/tmp/product"},
            "selected_providers": {"codespace": "local"},
        }
        with (
            mock.patch("scripts.gar_lib.workspaces.registry.load_config", return_value={"workspaces": [entry]}),
            mock.patch("scripts.gar_lib.workspaces.registry.saved_workspaces", return_value=[entry]),
        ):
            workspace = ConfigWorkspaceRegistry().get("Local/Product")

        self.assertEqual("ws_test", workspace.id)
        self.assertEqual("local", workspace.selected_environments["codespace"])

    def test_workspace_registry_requires_selector_for_multiple_entries(self) -> None:
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
            mock.patch("scripts.gar_lib.workspaces.registry.load_config", return_value={"workspaces": entries}),
            mock.patch("scripts.gar_lib.workspaces.registry.saved_workspaces", return_value=entries),
        ):
            with self.assertRaises(GarDomainError):
                ConfigWorkspaceRegistry().get(None)

    def test_local_build_environment_runs_product_hook_and_returns_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
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
        run.assert_called_once_with([str(hook)], cwd=root, check=False)

    def test_sim_build_dispatch_uses_resolved_build_environment(self) -> None:
        workspace = local_workspace(Path("/tmp/product"))
        artifact = mock.Mock()
        workspaces = mock.Mock()
        workspaces.get.return_value = workspace
        build_environment = mock.Mock()
        build_environment.build.return_value = artifact
        build_environments = mock.Mock()
        build_environments.for_workspace.return_value = build_environment
        services = SimCommandServices(
            workspaces=workspaces,
            build_environments=build_environments,
            artifacts=mock.Mock(),
            simulation_environments=mock.Mock(),
        )

        result = dispatch(SIM_BUILD, workspace_selector="Local/Product", services=services)

        self.assertIs(artifact, result)
        workspaces.get.assert_called_once_with("Local/Product")
        build_environments.for_workspace.assert_called_once_with(workspace)
        build_environment.build.assert_called_once_with(ArtifactKind.SIM_APP, workspace)

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
        artifacts.latest.return_value = artifact
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
        artifacts.sync_from_codespaces.assert_called_once_with(workspace)
        artifacts.latest.assert_called_once_with(ArtifactKind.SIM_APP, workspace)

    def test_wokwi_runtime_build_does_not_invoke_a_product_runtime_hook(self) -> None:
        workspace = local_workspace(Path("/tmp/product"))
        workspaces = mock.Mock()
        workspaces.get.return_value = workspace
        build_environments = mock.Mock()
        simulation_environment = mock.Mock(requires_runtime_artifact=False)
        simulation_environments = mock.Mock()
        simulation_environments.for_workspace.return_value = simulation_environment
        services = SimCommandServices(
            workspaces=workspaces,
            build_environments=build_environments,
            artifacts=mock.Mock(),
            simulation_environments=simulation_environments,
        )

        result = dispatch(SIM_RUNTIME_BUILD, workspace_selector="Local/Product", services=services)

        self.assertIsNone(result)
        build_environments.for_workspace.assert_not_called()

    def test_wokwi_runtime_deploy_does_not_require_an_artifact(self) -> None:
        workspace = local_workspace(Path("/tmp/product"))
        workspaces = mock.Mock()
        workspaces.get.return_value = workspace
        artifacts = mock.Mock()
        simulation_environment = mock.Mock(requires_runtime_artifact=False)
        simulation_environments = mock.Mock()
        simulation_environments.for_workspace.return_value = simulation_environment
        services = SimCommandServices(
            workspaces=workspaces,
            build_environments=mock.Mock(),
            artifacts=artifacts,
            simulation_environments=simulation_environments,
        )

        result = dispatch(SIM_RUNTIME_DEPLOY, workspace_selector="Local/Product", services=services)

        self.assertIsNone(result)
        artifacts.latest.assert_not_called()
        simulation_environment.deploy.assert_not_called()
