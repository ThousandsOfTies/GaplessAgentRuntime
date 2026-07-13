"""Build environment interface."""

from __future__ import annotations

from typing import Protocol

from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.workspace import Workspace


class BuildEnvironment(Protocol):
    def build(self, kind: ArtifactKind, workspace: Workspace) -> Artifact: ...

    def clean(self, kind: ArtifactKind, workspace: Workspace) -> None: ...
