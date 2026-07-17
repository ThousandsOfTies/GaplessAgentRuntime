"""Build environment interfaces and the artifact-kind-to-script build spec."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace


class BuildEnvironment(Protocol):
    def build(self, kind: ArtifactKind, workspace: Workspace) -> Artifact: ...

    def clean(self, kind: ArtifactKind, workspace: Workspace) -> None: ...


class BuildEnvironmentResolver(Protocol):
    def for_workspace(self, workspace: Workspace) -> BuildEnvironment: ...


@dataclass(frozen=True)
class BuildSpec:
    script: str


class ProductBuildSpecResolver:
    _SCRIPTS = {
        ArtifactKind.SIM_APP: "scripts/product-sim-build.sh",
        ArtifactKind.SIM_RUNTIME: "scripts/product-sim-env-build.sh",
        ArtifactKind.TARGET_APP: "scripts/product-target-build.sh",
    }

    def for_artifact(self, kind: ArtifactKind, workspace: Workspace) -> BuildSpec:
        del workspace
        script = self._SCRIPTS.get(kind)
        if script is None:
            raise GarDomainError(f"この artifact 種別の product build は未対応です: {kind.value}")
        return BuildSpec(script=script)
