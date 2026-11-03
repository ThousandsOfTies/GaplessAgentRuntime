"""Build environment contract and workspace-backed composition."""

from __future__ import annotations

from typing import Protocol

from scripts.gar_lib.artifacts.store import BuildArtifactStore
from scripts.gar_lib.build.codespaces import CodespacesBuildEnvironment
from scripts.gar_lib.build.docker import DockerBuildEnvironment
from scripts.gar_lib.build.local import LocalBuildEnvironment
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace


class BuildEnvironment(Protocol):
    def build(self, kind: ArtifactKind, workspace: Workspace) -> Artifact: ...

    def clean(self, kind: ArtifactKind, workspace: Workspace) -> None: ...

    def fetch(self, kind: ArtifactKind, workspace: Workspace) -> Artifact: ...


def build_environment_for(workspace: Workspace, artifacts: BuildArtifactStore) -> BuildEnvironment:
    """成果物をビルドするオブジェクトを作る。"""

    if workspace.selected_environments.simulator == 'product_hook':
        from scripts.gar_lib.simulation.runtime.product_hook import ProductSimulatorHook
        return ProductSimulatorHook(workspace, artifacts)
    backend = workspace.selected_environments.codespace
    if backend not in ("local", "docker", "native", "github_codespaces"):
        raise GarDomainError(f"build environment はまだ未対応です: {backend or '(未設定)'}")

    if backend == "github_codespaces":
        return CodespacesBuildEnvironment(artifacts)
    if backend == "native":
        return LocalBuildEnvironment(artifacts)
    return DockerBuildEnvironment(artifacts)
