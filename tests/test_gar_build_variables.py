from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from scripts.gar_lib.build.spec import ProductBuildSpecResolver
from scripts.gar_lib.core.artifact import ArtifactKind
from scripts.gar_lib.core.workspace import Workspace


def workspace_with(simulator: str | None, **sections: object) -> Workspace:
    return Workspace(
        id="ws",
        name="Local/Product",
        branch="Product",
        connection={"type": "local", "path": "/tmp/product"},
        selected_environments={"codespace": "local"} | ({"simulator": simulator} if simulator else {}),
        **sections,
    )


class BuildSpecVariablesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.specs = ProductBuildSpecResolver()

    def test_target_build_receives_selected_target(self) -> None:
        selected_workspace = workspace_with("ssh_remote", selected_target="raspberry-pi-5")

        spec = self.specs.for_artifact(ArtifactKind.TARGET_APP, selected_workspace)

        self.assertEqual({"GAR_TARGET": "raspberry-pi-5"}, spec.variables)

    def test_local_docker_builds_for_the_host_architecture(self) -> None:
        for machine, architecture in (("x86_64", "x86_64"), ("AMD64", "x86_64"), ("arm64", "aarch64")):
            with self.subTest(machine=machine), mock.patch("platform.machine", return_value=machine):
                spec = self.specs.for_artifact(ArtifactKind.SIM_RUNTIME, workspace_with("local_docker"))
            self.assertEqual("local_docker", spec.variables["GAR_SIM_ENVIRONMENT"])
            self.assertEqual(architecture, spec.variables["GAR_SIM_ARCH"])
            self.assertEqual("gcc", spec.variables["CC"])

    def test_ssh_remote_cross_compiles_for_aarch64_by_default(self) -> None:
        spec = self.specs.for_artifact(ArtifactKind.SIM_RUNTIME, workspace_with("ssh_remote"))

        self.assertEqual("aarch64", spec.variables["GAR_SIM_ARCH"])
        self.assertEqual("aarch64-linux-gnu-gcc", spec.variables["CC"])

    def test_configured_architecture_overrides_the_default(self) -> None:
        spec = self.specs.for_artifact(
            ArtifactKind.SIM_RUNTIME,
            workspace_with("ssh_remote", ec2={"host": "sim", "arch": "x86_64"}),
        )

        self.assertEqual("x86_64", spec.variables["GAR_SIM_ARCH"])

    def test_docker_and_ssh_remote_produce_different_build_commands(self) -> None:
        docker = self.specs.for_artifact(ArtifactKind.SIM_RUNTIME, workspace_with("local_docker"))
        remote = self.specs.for_artifact(ArtifactKind.SIM_RUNTIME, workspace_with("ssh_remote"))

        self.assertEqual(docker.script, remote.script)
        self.assertNotEqual(docker.variables, remote.variables)

    def test_target_build_is_not_affected_by_the_simulator_choice(self) -> None:
        spec = self.specs.for_artifact(ArtifactKind.TARGET_APP, workspace_with("local_docker"))

        self.assertEqual({}, dict(spec.variables))


class LocalBuildEnvironmentVariablesTest(unittest.TestCase):
    def test_build_hook_receives_the_simulation_architecture(self) -> None:
        import tempfile
        from unittest import mock

        from scripts.gar_lib.build.local import LocalBuildEnvironment

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hook = root / "scripts" / "product-sim-env-build.sh"
            hook.parent.mkdir()
            hook.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            workspace = Workspace(
                id="ws",
                name="Local/Product",
                branch="Product",
                connection={"type": "local", "path": str(root)},
                selected_environments={"codespace": "local", "simulator": "local_docker"},
            )
            artifacts = mock.Mock()
            completed = mock.Mock(returncode=0)
            with (
                mock.patch("platform.machine", return_value="AMD64"),
                mock.patch("scripts.gar_lib.build.local.subprocess.run", return_value=completed) as run,
            ):
                LocalBuildEnvironment(artifacts).build(ArtifactKind.SIM_RUNTIME, workspace)

        env = run.call_args.kwargs["env"]
        self.assertEqual("gcc", env["CC"])
        self.assertEqual("local_docker", env["GAR_SIM_ENVIRONMENT"])
        self.assertEqual("x86_64", env["GAR_SIM_ARCH"])


class CodespacesBuildEnvironmentVariablesTest(unittest.TestCase):
    def test_remote_command_carries_the_variable_assignments(self) -> None:
        from unittest import mock

        from scripts.gar_lib.build.codespaces import CodespacesBuildEnvironment

        workspace = Workspace(
            id="ws",
            name="Codespaces/Product",
            branch="Product",
            connection={"type": "codespaces", "codespace": "cs-1", "path": "/workspaces/p"},
            selected_environments={"codespace": "github_codespaces", "simulator": "ssh_remote"},
        )
        artifacts = mock.Mock()
        completed = mock.Mock(returncode=0)
        with mock.patch("scripts.gar_lib.build.codespaces.subprocess.run", return_value=completed) as run:
            CodespacesBuildEnvironment(artifacts).build(ArtifactKind.SIM_RUNTIME, workspace)

        command = run.call_args.args[0][-1]
        self.assertIn("CC=aarch64-linux-gnu-gcc", command)
        self.assertIn("GAR_SIM_ARCH=aarch64", command)
        self.assertIn("scripts/product-sim-env-build.sh", command)


if __name__ == "__main__":
    unittest.main()
