"""Serial-flashed physical target environment."""

from __future__ import annotations

from scripts.gar_lib.access.base import ArtifactInstaller
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError


class SerialTargetEnvironment:
    def __init__(self, installer: ArtifactInstaller):
        self.installer = installer

    def deploy(self, artifact: Artifact) -> None:
        if artifact.kind is not ArtifactKind.TARGET_APP:
            raise GarDomainError(f"serial targetへ配置できないartifactです: {artifact.kind.value}")
        result = self.installer.install(artifact)
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.stderr:
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
        if result.returncode != 0:
            raise GarDomainError(f"serial targetへの書き込みに失敗しました (exit {result.returncode})")
