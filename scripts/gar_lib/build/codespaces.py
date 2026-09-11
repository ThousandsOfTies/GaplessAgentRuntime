"""Build product artifacts in a GitHub Codespace and materialize them locally."""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Mapping

from scripts.gar_lib.artifacts.store import BuildArtifactStore
from scripts.gar_lib.build.spec import ProductBuildSpecResolver
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace


class CodespacesBuildEnvironment:
    def __init__(self, artifacts: BuildArtifactStore, specs: ProductBuildSpecResolver | None = None):
        self.artifacts = artifacts
        self.specs = specs or ProductBuildSpecResolver()

    def build(self, kind: ArtifactKind, workspace: Workspace) -> Artifact:
        spec = self.specs.for_artifact(kind, workspace)
        command = (
            f"cd {shlex.quote(workspace.remote_root)} && " f"{_assignments(spec.variables)}{shlex.quote(spec.script)}"
        )
        result = subprocess.run(
            ["gh", "codespace", "ssh", "-c", workspace.codespace_name, "--", command],
            check=False,
        )
        if result.returncode != 0:
            raise GarDomainError(f"{kind.value} Codespaces build が失敗しました (exit {result.returncode})")
        return self.artifacts.sync_from_codespaces(kind, workspace)

    def clean(self, kind: ArtifactKind, workspace: Workspace) -> None:
        spec = self.specs.for_artifact(kind, workspace)
        command = (
            f"cd {shlex.quote(workspace.remote_root)} && "
            f"{_assignments(spec.variables)}{shlex.quote(spec.script)} clean"
        )
        result = subprocess.run(
            ["gh", "codespace", "ssh", "-c", workspace.codespace_name, "--", command],
            check=False,
        )
        if result.returncode != 0:
            raise GarDomainError(f"{kind.value} Codespaces clean が失敗しました (exit {result.returncode})")
        self.artifacts.remove(kind, workspace)

    def fetch(self, kind: ArtifactKind, workspace: Workspace) -> Artifact:
        return self.artifacts.sync_from_codespaces(kind, workspace)


def _assignments(variables: Mapping[str, str]) -> str:
    return "".join(f"{name}={shlex.quote(value)} " for name, value in sorted(variables.items()))
