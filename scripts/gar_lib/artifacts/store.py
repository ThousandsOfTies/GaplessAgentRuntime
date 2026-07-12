"""Artifact storage independent from build and runtime environments."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from scripts.gar_lib.artifacts.manifest import load_deploy_files
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace


class ArtifactStore(Protocol):
    def latest(self, kind: ArtifactKind, workspace: Workspace) -> Artifact: ...


class LocalArtifactStore:
    _MANIFEST_SECTIONS = {
        ArtifactKind.SIM_APP: "app",
        ArtifactKind.SIM_RUNTIME: "sim_env",
        ArtifactKind.TARGET_APP: "app",
    }

    def __init__(self, relative_root: Path = Path("artifacts/from-codespace")):
        self.relative_root = relative_root

    def latest(self, kind: ArtifactKind, workspace: Workspace) -> Artifact:
        bundle_path = workspace.local_root / self.relative_root
        section = self._MANIFEST_SECTIONS[kind]
        if load_deploy_files(bundle_path, section) is None:
            raise GarDomainError(
                f"{kind.value} artifact がありません。先に build を実行してください: {bundle_path}"
            )
        return Artifact(kind=kind, workspace=workspace, bundle_path=bundle_path)
