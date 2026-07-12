"""Artifact storage independent from build and runtime environments."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from scripts.gar_lib.artifacts.manifest import fetch_codespace_artifacts, load_deploy_files
from scripts.gar_lib.config import PROJECT_ROOT
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
        bundle_path = self.bundle_path(workspace)
        section = self._MANIFEST_SECTIONS[kind]
        if load_deploy_files(bundle_path, section) is None:
            raise GarDomainError(
                f"{kind.value} artifact がありません。先に build を実行してください: {bundle_path}"
            )
        return Artifact(kind=kind, workspace=workspace, bundle_path=bundle_path)

    def sync_from_codespaces(self, workspace: Workspace) -> None:
        result = fetch_codespace_artifacts(
            self.bundle_path(workspace),
            codespace=workspace.codespace_name,
            remote_root=f"{workspace.remote_root}/{self.relative_root.as_posix()}",
        )
        if result != 0:
            raise GarDomainError(f"Codespaces artifact の取得に失敗しました (exit {result})")

    def bundle_path(self, workspace: Workspace) -> Path:
        if workspace.connection_type == "local":
            return workspace.local_root / self.relative_root
        return PROJECT_ROOT / ".gar" / "artifacts" / workspace.id
