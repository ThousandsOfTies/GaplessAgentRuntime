"""Legacy native build backend for explicit Linux-host compatibility."""

from __future__ import annotations

import os
import subprocess
import sys

from scripts.gar_lib.access.display import run_displayed
from scripts.gar_lib.artifacts.store import BuildArtifactStore
from scripts.gar_lib.build.spec import ProductBuildSpecResolver
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace


class LocalBuildEnvironment:
    def __init__(self, artifacts: BuildArtifactStore, specs: ProductBuildSpecResolver | None = None):
        self.artifacts = artifacts
        self.specs = specs or ProductBuildSpecResolver()

    @staticmethod
    def _command(script):
        # Portable Product hooks can opt into Python without a shell/WSL.
        python_hook = script.with_suffix(".py")
        if python_hook.is_file():
            return [sys.executable, str(python_hook)]
        if not script.is_file():
            raise GarDomainError(f"product build hook が見つかりません: {script}")
        return [str(script)]

    def build(self, kind: ArtifactKind, workspace: Workspace) -> Artifact:
        spec = self.specs.for_artifact(kind, workspace)
        script = workspace.local_root / spec.script
        result = run_displayed(
            self._command(script),
            cwd=workspace.local_root,
            env={**os.environ, **spec.variables},
            runner=subprocess.run,
            check=False,
        )
        if result.returncode != 0:
            raise GarDomainError(f"{kind.value} build が失敗しました (exit {result.returncode})")
        return self.artifacts.capture(kind, workspace)

    def clean(self, kind: ArtifactKind, workspace: Workspace) -> None:
        spec = self.specs.for_artifact(kind, workspace)
        script = workspace.local_root / spec.script
        result = run_displayed(
            [*self._command(script), "clean"],
            cwd=workspace.local_root,
            env={**os.environ, **spec.variables},
            runner=subprocess.run,
            check=False,
        )
        if result.returncode != 0:
            raise GarDomainError(f"{kind.value} clean が失敗しました (exit {result.returncode})")
        self.artifacts.remove(kind, workspace)

    def fetch(self, kind: ArtifactKind, workspace: Workspace) -> Artifact:
        # native build output is already present below workspace.local_root.
        return self.artifacts.latest(kind, workspace)
