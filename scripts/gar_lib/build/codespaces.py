"""Build product artifacts in a GitHub Codespace and materialize them locally."""

from __future__ import annotations

import shlex
import subprocess

from scripts.gar_lib.artifacts.store import LocalArtifactStore
from scripts.gar_lib.build.spec import ProductBuildSpecResolver
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace


class CodespacesBuildEnvironment:
    def __init__(self, artifacts: LocalArtifactStore, specs: ProductBuildSpecResolver | None = None):
        self.artifacts = artifacts
        self.specs = specs or ProductBuildSpecResolver()

    def build(self, kind: ArtifactKind, workspace: Workspace) -> Artifact:
        spec = self.specs.for_artifact(kind, workspace)
        command = f"cd {shlex.quote(workspace.remote_root)} && {shlex.quote(spec.script)}"
        result = subprocess.run(
            ["gh", "codespace", "ssh", "-c", workspace.codespace_name, "--", command],
            check=False,
        )
        if result.returncode != 0:
            raise GarDomainError(f"{kind.value} Codespaces build が失敗しました (exit {result.returncode})")
        self.artifacts.sync_from_codespaces(workspace)
        return self.artifacts.latest(kind, workspace)

    def clean(self, kind: ArtifactKind, workspace: Workspace) -> None:
        spec = self.specs.for_artifact(kind, workspace)
        command = (
            f"cd {shlex.quote(workspace.remote_root)} && "
            f"{shlex.quote(spec.script)} clean"
        )
        result = subprocess.run(
            ["gh", "codespace", "ssh", "-c", workspace.codespace_name, "--", command],
            check=False,
        )
        if result.returncode != 0:
            raise GarDomainError(f"{kind.value} Codespaces clean が失敗しました (exit {result.returncode})")
