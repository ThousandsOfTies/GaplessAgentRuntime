"""Choose a concrete build environment from workspace settings."""

from __future__ import annotations

from scripts.gar_lib.artifacts.store import LocalArtifactStore
from scripts.gar_lib.build.base import BuildEnvironment
from scripts.gar_lib.build.codespaces import CodespacesBuildEnvironment
from scripts.gar_lib.build.local import LocalBuildEnvironment
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace


class ConfigBuildEnvironmentResolver:
    def __init__(self, artifacts: LocalArtifactStore):
        self.artifacts = artifacts

    def for_workspace(self, workspace: Workspace) -> BuildEnvironment:
        environment_id = workspace.selected_environments.get("codespace")
        if environment_id == "local":
            return LocalBuildEnvironment(self.artifacts)
        if environment_id == "github_codespaces":
            return CodespacesBuildEnvironment(self.artifacts)
        raise GarDomainError(f"build environment はまだ未対応です: {environment_id or '(未設定)'}")
