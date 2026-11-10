"""Build Product artifacts through Windows WSL Containers."""

from __future__ import annotations

import json

from scripts.gar_lib.access.docker import DockerCliCommandChannel
from scripts.gar_lib.access.wslc import WslcCliChannel
from scripts.gar_lib.artifacts.store import BuildArtifactStore
from scripts.gar_lib.build.docker import BUILD_SPEC_FINGERPRINT_LABEL, DockerBuildEnvironment
from scripts.gar_lib.build.spec import ProductBuildSpecResolver
from scripts.gar_lib.core.artifact import ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace


class WslcBuildEnvironment(DockerBuildEnvironment):
    """Reuse container hooks, caches and artifact capture with a WSLC driver."""

    runtime_name = "WSLC"

    def __init__(
        self,
        artifacts: BuildArtifactStore,
        *,
        wslc: DockerCliCommandChannel | None = None,
        specs: ProductBuildSpecResolver | None = None,
    ):
        super().__init__(artifacts, docker=wslc or WslcCliChannel(), specs=specs)

    def _run_hook(self, kind: ArtifactKind, workspace: Workspace, *, action: str | None = None) -> None:
        if workspace.build.docker_socket:
            raise GarDomainError(
                "WSLC build は build.docker_socket に対応していません。Docker build環境を選択してください。"
            )
        super()._run_hook(kind, workspace, action=action)

    def _image_fingerprint(self, image: str) -> str | None:
        # WSLC accepts JSON, but not Docker's Go template expressions.
        inspection = self.docker.run(("image", "inspect", "--format", "json", image))
        if inspection.returncode != 0:
            return None
        try:
            data = json.loads(inspection.stdout)
            if isinstance(data, list):
                data = data[0]
            labels = (data.get("Config") or {}).get("Labels") or {}
            fingerprint = labels.get(BUILD_SPEC_FINGERPRINT_LABEL)
        except (ValueError, TypeError, AttributeError, IndexError) as error:
            raise GarDomainError("WSLC image inspect の JSON を読み取れませんでした。") from error
        return fingerprint if isinstance(fingerprint, str) else None
