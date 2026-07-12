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
        script = self._SCRIPTS.get(kind)
        if script is None:
            raise GarDomainError(f"この artifact 種別の product build は未対応です: {kind.value}")
        if not (workspace.local_root / script).is_file():
            raise GarDomainError(f"product build hook が見つかりません: {workspace.local_root / script}")
        return BuildSpec(script=script)
