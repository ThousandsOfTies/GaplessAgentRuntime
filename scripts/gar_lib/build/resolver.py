"""Choose a concrete build environment from workspace settings."""

from __future__ import annotations

from typing import Protocol

from scripts.gar_lib.artifacts.store import ArtifactStore
from scripts.gar_lib.build.base import BuildEnvironment
from scripts.gar_lib.build.local import LocalBuildEnvironment
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace


class BuildEnvironmentResolver(Protocol):
    def for_workspace(self, workspace: Workspace) -> BuildEnvironment: ...


class ConfigBuildEnvironmentResolver:
    def __init__(self, artifacts: ArtifactStore):
        self.artifacts = artifacts

    def for_workspace(self, workspace: Workspace) -> BuildEnvironment:
        environment_id = workspace.selected_environments.get("codespace")
        if environment_id == "local":
            return LocalBuildEnvironment(self.artifacts)
        raise GarDomainError(f"build environment はまだ未対応です: {environment_id or '(未設定)'}")
