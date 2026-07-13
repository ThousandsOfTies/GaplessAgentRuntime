"""File-oriented physical targets composed from command and file channels."""

from __future__ import annotations

import shlex
from posixpath import dirname

from scripts.gar_lib.access.base import CommandChannel, FileChannel
from scripts.gar_lib.artifacts.manifest import (
    load_deploy_files,
    resolve_artifact_src,
    target_dest_path,
)
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError


class FileTransferTargetEnvironment:
    def __init__(
        self,
        command_channel: CommandChannel,
        file_channel: FileChannel,
        *,
        base_destination: str = "/home/user",
    ):
        self.command_channel = command_channel
        self.file_channel = file_channel
        self.base_destination = base_destination

    def deploy(self, artifact: Artifact) -> None:
        if artifact.kind is not ArtifactKind.TARGET_APP:
            raise GarDomainError(f"targetへ配置できないartifactです: {artifact.kind.value}")
        loaded = load_deploy_files(artifact.bundle_path, "app")
        if loaded is None:
            raise GarDomainError(f"target artifact manifestを読み込めません: {artifact.bundle_path}")
        bundle_root, files = loaded

        for entry in files:
            source = resolve_artifact_src(bundle_root, entry["src"])
            if source is None:
                raise GarDomainError(f"target artifact sourceがありません: {entry['src']}")
            destination = self._destination(entry["dest"])
            parent = dirname(destination)
            if parent:
                prepared = self.command_channel.run(f"mkdir -p {shlex.quote(parent)}")
                if prepared.returncode != 0:
                    raise GarDomainError(
                        f"target artifact配置先を作成できません (exit {prepared.returncode})"
                    )
            transferred = self.file_channel.push(source, destination)
            if transferred.returncode != 0:
                raise GarDomainError(f"target artifact転送に失敗しました (exit {transferred.returncode})")

            mode = entry.get("mode")
            if isinstance(mode, str):
                result = self.command_channel.run(
                    f"chmod {shlex.quote(mode)} {shlex.quote(destination)}"
                )
                if result.returncode != 0:
                    raise GarDomainError(f"target artifactのmode設定に失敗しました (exit {result.returncode})")

    def _destination(self, destination: str) -> str:
        if destination == "~":
            return self.base_destination
        if destination.startswith("~/"):
            return f"{self.base_destination.rstrip('/')}/{destination[2:]}"
        return target_dest_path(destination, self.base_destination)
