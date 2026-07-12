"""Resolve product build recipes without choosing where they run."""

from __future__ import annotations

from dataclasses import dataclass

from scripts.gar_lib.core.artifact import ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace


@dataclass(frozen=True)
class BuildSpec:
    script: str


class ProductBuildSpecResolver:
    _SCRIPTS = {
        ArtifactKind.SIM_APP: "scripts/product-sim-build.sh",
        ArtifactKind.SIM_RUNTIME: "scripts/product-sim-env-build.sh",
    }

    def for_artifact(self, kind: ArtifactKind, workspace: Workspace) -> BuildSpec:
        del workspace
        script = self._SCRIPTS.get(kind)
        if script is None:
            raise GarDomainError(f"この artifact 種別の product build は未対応です: {kind.value}")
        return BuildSpec(script=script)
