"""Run Product build hooks in a Linux container owned by the Build layer."""

from __future__ import annotations

import hashlib
import os
from pathlib import PurePosixPath

from scripts.gar_lib.access.docker import DockerCliChannel, DockerCliCommandChannel
from scripts.gar_lib.artifacts.store import BuildArtifactStore
from scripts.gar_lib.build.spec import ProductBuildSpecResolver
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.config import PROJECT_ROOT
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace

DEFAULT_BUILD_IMAGE = "gar-build-env:ubuntu-24.04"
CONTAINER_WORKSPACE = PurePosixPath("/workspace")
BUILD_CACHE = PurePosixPath("/gar-build-cache")
DOCKER_SOCKET = "/var/run/docker.sock"
BUILD_SPEC_FINGERPRINT_LABEL = "io.gapless-agent-runtime.build-spec"


def build_cache_volume_name(workspace_id: str) -> str:
    """Keep cache names stable and safe without exposing workspace paths."""

    identity = hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()[:16]
    return f"gar-build-cache-{identity}"


class DockerBuildEnvironment:
    """Bind a Product workspace and execute its hook through container Bash."""

    runtime_name = "Docker"

    def __init__(
        self,
        artifacts: BuildArtifactStore,
        *,
        docker: DockerCliCommandChannel | None = None,
        specs: ProductBuildSpecResolver | None = None,
    ):
        self.artifacts = artifacts
        self.docker = docker or DockerCliChannel()
        self.specs = specs or ProductBuildSpecResolver()

    def build(self, kind: ArtifactKind, workspace: Workspace) -> Artifact:
        self._run_hook(kind, workspace)
        return self.artifacts.capture(kind, workspace)

    def clean(self, kind: ArtifactKind, workspace: Workspace) -> None:
        self._run_hook(kind, workspace, action="clean")
        self.artifacts.remove(kind, workspace)

    def fetch(self, kind: ArtifactKind, workspace: Workspace) -> Artifact:
        return self.artifacts.latest(kind, workspace)

    def _run_hook(
        self,
        kind: ArtifactKind,
        workspace: Workspace,
        *,
        action: str | None = None,
    ) -> None:
        spec = self.specs.for_artifact(kind, workspace)
        script = workspace.local_root / spec.script
        if not script.is_file():
            raise GarDomainError(f"product build hook が見つかりません: {script}")

        image = workspace.build.image or DEFAULT_BUILD_IMAGE
        if image == DEFAULT_BUILD_IMAGE:
            self._ensure_default_image(image)

        arguments: list[str] = [
            "run",
            "--rm",
            "--mount",
            f"type=bind,source={workspace.local_root},target={CONTAINER_WORKSPACE}",
            "--workdir",
            str(CONTAINER_WORKSPACE),
            "--env",
            "HOME=/tmp/gar-home",
        ]
        if workspace.build.cache:
            cache_mount = f"type=volume,source={build_cache_volume_name(workspace.id)},target={BUILD_CACHE}"
            self._prepare_cache_root(image, cache_mount)
            arguments.extend(("--mount", cache_mount, "--env", f"GAR_BUILD_CACHE={BUILD_CACHE}"))
        if workspace.build.docker_socket:
            arguments.extend(
                (
                    "--mount",
                    f"type=bind,source={DOCKER_SOCKET},target={DOCKER_SOCKET}",
                )
            )
        self._add_posix_identity(arguments, include_socket_group=workspace.build.docker_socket)
        for name, value in sorted(spec.variables.items()):
            arguments.extend(("--env", f"{name}={value}"))

        container_script = CONTAINER_WORKSPACE / PurePosixPath(spec.script)
        arguments.extend((image, "bash", str(container_script)))
        if action is not None:
            arguments.append(action)

        result = self.docker.run(tuple(arguments))
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            suffix = f": {detail}" if detail else ""
            raise GarDomainError(f"{kind.value} {action or 'build'} が失敗しました (exit {result.returncode}){suffix}")

    def _prepare_cache_root(self, image: str, cache_mount: str) -> None:
        if os.name == "nt" or not hasattr(os, "getuid") or not hasattr(os, "getgid"):
            return
        # New named volumes are root-owned. Only change the fixed cache root,
        # without mounting the Product or changing existing cache contents.
        result = self.docker.run(
            (
                "run",
                "--rm",
                "--mount",
                cache_mount,
                "--user",
                "0:0",
                image,
                "chown",
                f"{os.getuid()}:{os.getgid()}",
                str(BUILD_CACHE),
            )
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise GarDomainError(
                f"{self.runtime_name} build cacheを準備できませんでした (exit {result.returncode})"
                + (f": {detail}" if detail else "")
            )

    def _ensure_default_image(self, image: str) -> None:
        context = PROJECT_ROOT / "infra" / "build"
        fingerprint = hashlib.sha256((context / "Dockerfile").read_bytes()).hexdigest()
        if self._image_fingerprint(image) == fingerprint:
            return
        result = self.docker.run(
            (
                "build",
                "--build-arg",
                f"GAR_BUILD_SPEC_FINGERPRINT={fingerprint}",
                "--tag",
                image,
                str(context),
            )
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise GarDomainError(
                f"{self.runtime_name} build imageを作成できませんでした (exit {result.returncode})"
                + (f": {detail}" if detail else "")
            )

    def _image_fingerprint(self, image: str) -> str | None:
        inspection = self.docker.run(
            (
                "image",
                "inspect",
                "--format",
                f'{{{{ index .Config.Labels "{BUILD_SPEC_FINGERPRINT_LABEL}" }}}}',
                image,
            )
        )
        return inspection.stdout.strip() if inspection.returncode == 0 else None

    @staticmethod
    def _add_posix_identity(arguments: list[str], *, include_socket_group: bool) -> None:
        if os.name == "nt" or not hasattr(os, "getuid") or not hasattr(os, "getgid"):
            return
        arguments.extend(("--user", f"{os.getuid()}:{os.getgid()}"))
        if not include_socket_group:
            return
        try:
            socket_group = os.stat(DOCKER_SOCKET).st_gid
        except OSError:
            return
        arguments.extend(("--group-add", str(socket_group)))
