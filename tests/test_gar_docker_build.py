from __future__ import annotations

import hashlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.gar_lib.access.channel import AccessResult
from scripts.gar_lib.build.docker import (
    BUILD_SPEC_FINGERPRINT_LABEL,
    DEFAULT_BUILD_IMAGE,
    DOCKER_SOCKET,
    DockerBuildEnvironment,
    build_cache_volume_name,
)
from scripts.gar_lib.core.artifact import ArtifactKind
from scripts.gar_lib.core.config import PROJECT_ROOT
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace


def _workspace(
    root: Path, *, image: str | None = "gar-build:test", docker_socket: bool = False, cache: bool = False
) -> Workspace:
    build = {"docker_socket": docker_socket, "cache": cache}
    if image is not None:
        build["image"] = image
    return Workspace(
        id="ws-docker-build",
        name="Local/Product",
        branch="Product",
        connection={"type": "local", "path": str(root)},
        selected_environments={
            "codespace": "local",
            "simulator": "ssh_remote",
            "simulation_host": "virtualbox",
        },
        build=build,
        simulation_host={"host": "gar-sim-local"},
        virtualbox={"vm": "GAR Ubuntu Sim"},
    )


def _hook(root: Path, kind: ArtifactKind) -> Path:
    names = {
        ArtifactKind.SIM_APP: "product-sim-build.sh",
        ArtifactKind.SIM_RUNTIME: "product-sim-env-build.sh",
        ArtifactKind.TARGET_APP: "product-target-build.sh",
    }
    path = root / "scripts" / names[kind]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    return path


class DockerBuildEnvironmentTest(unittest.TestCase):
    def test_current_default_image_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _hook(root, ArtifactKind.SIM_APP)
            workspace = _workspace(root, image=None)
            fingerprint = hashlib.sha256((PROJECT_ROOT / "infra" / "build" / "Dockerfile").read_bytes()).hexdigest()
            docker = mock.Mock()
            docker.run.side_effect = [
                AccessResult(("docker",), 0, fingerprint + "\n"),
                AccessResult(("docker",), 0),
            ]
            artifacts = mock.Mock()

            DockerBuildEnvironment(artifacts, docker=docker).build(ArtifactKind.SIM_APP, workspace)

        self.assertEqual(2, docker.run.call_count)
        self.assertEqual("run", docker.run.call_args_list[1].args[0][0])

    def test_build_runs_product_hook_in_configured_image_and_captures_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _hook(root, ArtifactKind.SIM_APP)
            workspace = _workspace(root)
            docker = mock.Mock()
            docker.run.return_value = AccessResult(("docker",), 0)
            artifact = mock.Mock()
            artifacts = mock.Mock()
            artifacts.capture.return_value = artifact

            result = DockerBuildEnvironment(artifacts, docker=docker).build(ArtifactKind.SIM_APP, workspace)
            arguments = docker.run.call_args.args[0]

        self.assertIs(artifact, result)
        self.assertEqual("run", arguments[0])
        self.assertIn(f"type=bind,source={root.resolve()},target=/workspace", arguments)
        self.assertNotIn(DOCKER_SOCKET, " ".join(arguments))
        self.assertNotIn("GAR_BUILD_CACHE", " ".join(arguments))
        self.assertNotIn("type=volume", " ".join(arguments))
        self.assertIn("GAR_SIM_ENVIRONMENT=ssh_remote", arguments)
        self.assertIn("GAR_SIM_ARCH=x86_64", arguments)
        self.assertEqual(
            ("gar-build:test", "bash", "/workspace/scripts/product-sim-build.sh"),
            arguments[-3:],
        )
        artifacts.capture.assert_called_once_with(ArtifactKind.SIM_APP, workspace)

    def test_opt_in_cache_mount_is_reused_by_workspace_identity_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _hook(root, ArtifactKind.TARGET_APP)
            workspace = _workspace(root, cache=True)
            docker = mock.Mock()
            docker.run.return_value = AccessResult(("docker",), 0)
            artifacts = mock.Mock()
            environment = DockerBuildEnvironment(artifacts, docker=docker)
            with mock.patch("scripts.gar_lib.build.docker.os", SimpleNamespace(name="nt")):
                environment.build(ArtifactKind.TARGET_APP, workspace)
                environment.build(ArtifactKind.TARGET_APP, replace(workspace, name="Local/Renamed"))
                environment.build(ArtifactKind.TARGET_APP, replace(workspace, id="ws-another"))

        self.assertEqual(3, docker.run.call_count)
        first, same, another = (call.args[0] for call in docker.run.call_args_list)
        mount = f"type=volume,source={build_cache_volume_name(workspace.id)},target=/gar-build-cache"
        self.assertIn(mount, first)
        self.assertIn(mount, same)
        self.assertNotIn(mount, another)
        self.assertIn("GAR_BUILD_CACHE=/gar-build-cache", first)
        self.assertNotIn("chown", first)
        self.assertRegex(build_cache_volume_name("untrusted/path, 日本語"), r"^gar-build-cache-[0-9a-f]{16}$")

    def test_posix_cache_initializes_only_the_volume_root_for_the_build_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _hook(root, ArtifactKind.TARGET_APP)
            workspace = _workspace(root, cache=True)
            docker = mock.Mock()
            docker.run.return_value = AccessResult(("docker",), 0)
            artifacts = mock.Mock()
            posix = SimpleNamespace(name="posix", getuid=lambda: 1001, getgid=lambda: 1002)
            with mock.patch("scripts.gar_lib.build.docker.os", posix):
                DockerBuildEnvironment(artifacts, docker=docker).build(ArtifactKind.TARGET_APP, workspace)

        self.assertEqual(2, docker.run.call_count)
        initialization = docker.run.call_args_list[0].args[0]
        mount = f"type=volume,source={build_cache_volume_name(workspace.id)},target=/gar-build-cache"
        self.assertEqual(
            (
                "run",
                "--rm",
                "--mount",
                mount,
                "--user",
                "0:0",
                "gar-build:test",
                "chown",
                "1001:1002",
                "/gar-build-cache",
            ),
            initialization,
        )
        self.assertNotIn("type=bind", " ".join(initialization))
        self.assertNotIn("-R", initialization)
        arguments = docker.run.call_args_list[1].args[0]
        self.assertIn(mount, arguments)
        self.assertEqual("1001:1002", arguments[arguments.index("--user") + 1])

    def test_failed_cache_initialization_aborts_before_the_product_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _hook(root, ArtifactKind.TARGET_APP)
            workspace = _workspace(root, cache=True)
            docker = mock.Mock()
            docker.run.return_value = AccessResult(("docker",), 13, "", "permission denied")
            artifacts = mock.Mock()
            posix = SimpleNamespace(name="posix", getuid=lambda: 1001, getgid=lambda: 1002)
            with mock.patch("scripts.gar_lib.build.docker.os", posix):
                with self.assertRaisesRegex(GarDomainError, "permission denied"):
                    DockerBuildEnvironment(artifacts, docker=docker).build(ArtifactKind.TARGET_APP, workspace)

        docker.run.assert_called_once()
        artifacts.capture.assert_not_called()

    def test_default_image_is_built_and_docker_socket_is_mounted_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _hook(root, ArtifactKind.SIM_RUNTIME)
            workspace = _workspace(root, image=None, docker_socket=True)
            docker = mock.Mock()
            docker.run.side_effect = [
                AccessResult(("docker",), 1, "", "No such image"),
                AccessResult(("docker",), 0),
                AccessResult(("docker",), 0),
            ]
            artifacts = mock.Mock()

            DockerBuildEnvironment(artifacts, docker=docker).build(ArtifactKind.SIM_RUNTIME, workspace)

        self.assertEqual(
            mock.call(
                (
                    "image",
                    "inspect",
                    "--format",
                    f'{{{{ index .Config.Labels "{BUILD_SPEC_FINGERPRINT_LABEL}" }}}}',
                    DEFAULT_BUILD_IMAGE,
                )
            ),
            docker.run.call_args_list[0],
        )
        build_arguments = docker.run.call_args_list[1].args[0]
        self.assertEqual("build", build_arguments[0])
        self.assertIn("--build-arg", build_arguments)
        self.assertIn("--tag", build_arguments)
        self.assertIn(DEFAULT_BUILD_IMAGE, build_arguments)
        self.assertEqual(str(PROJECT_ROOT / "infra" / "build"), build_arguments[-1])
        run_arguments = docker.run.call_args_list[2].args[0]
        self.assertIn(f"type=bind,source={DOCKER_SOCKET},target={DOCKER_SOCKET}", run_arguments)
        self.assertEqual(DEFAULT_BUILD_IMAGE, run_arguments[-3])

    def test_failed_hook_does_not_capture_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _hook(root, ArtifactKind.SIM_APP)
            workspace = _workspace(root)
            docker = mock.Mock()
            docker.run.return_value = AccessResult(("docker",), 17, "", "compile failed")
            artifacts = mock.Mock()

            with self.assertRaisesRegex(GarDomainError, "compile failed"):
                DockerBuildEnvironment(artifacts, docker=docker).build(ArtifactKind.SIM_APP, workspace)

        artifacts.capture.assert_not_called()

    def test_clean_passes_action_to_hook_then_removes_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _hook(root, ArtifactKind.TARGET_APP)
            workspace = _workspace(root)
            docker = mock.Mock()
            docker.run.return_value = AccessResult(("docker",), 0)
            artifacts = mock.Mock()

            DockerBuildEnvironment(artifacts, docker=docker).clean(ArtifactKind.TARGET_APP, workspace)
            arguments = docker.run.call_args.args[0]

        self.assertEqual(
            ("gar-build:test", "bash", "/workspace/scripts/product-target-build.sh", "clean"),
            arguments[-4:],
        )
        artifacts.remove.assert_called_once_with(ArtifactKind.TARGET_APP, workspace)


if __name__ == "__main__":
    unittest.main()
