"""ESP32 serial artifact adapter for the target architecture."""

from __future__ import annotations

from pathlib import Path

from scripts.gar_lib.access.base import CommandResult
from scripts.gar_lib.artifacts.manifest import load_deploy_files, resolve_artifact_src
from scripts.gar_lib.core.artifact import Artifact
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.environments.registry.target.esp32_esptool import run_esp32_flash_command
from scripts.gar_lib.targets.esp32 import FLASH_LAYOUT


class Esp32ArtifactInstaller:
    def __init__(self, port: str):
        self.port = port

    def install(self, artifact: Artifact) -> CommandResult:
        artifact_dir = self._artifact_dir(artifact)
        returncode = run_esp32_flash_command(
            artifact_dir=str(artifact_dir),
            port=self.port,
        )
        return CommandResult(
            argv=("esptool", "--port", self.port, str(artifact_dir)),
            returncode=returncode,
        )

    @staticmethod
    def _artifact_dir(artifact: Artifact) -> Path:
        required = {name for _, name in FLASH_LAYOUT}
        if all((artifact.bundle_path / name).is_file() for name in required):
            return artifact.bundle_path

        loaded = load_deploy_files(artifact.bundle_path, "app")
        if loaded is None:
            raise GarDomainError(f"ESP32 artifact manifestを読み込めません: {artifact.bundle_path}")
        bundle_root, files = loaded
        candidates: list[Path] = []
        for entry in files:
            source = resolve_artifact_src(bundle_root, entry["src"])
            if source is None:
                continue
            candidates.append(source if source.is_dir() else source.parent)
        for candidate in candidates:
            if all((candidate / name).is_file() for name in required):
                return candidate
        raise GarDomainError("ESP32 artifactにfirmware一式がありません。")
