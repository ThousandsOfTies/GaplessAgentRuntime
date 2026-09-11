"""Report completed artifact placements without implying runtime convergence."""

from __future__ import annotations

from collections.abc import Sequence

from scripts.gar_lib.core.artifact import Artifact
from scripts.gar_lib.core.errors import GarDomainError


def placement_payload(artifacts: Sequence[Artifact]) -> dict[str, object]:
    return {
        "placed_artifacts": [
            {"kind": artifact.kind.value, "path": str(artifact.bundle_path)} for artifact in artifacts
        ],
        "running": None,
        "verification": "not_checked",
        "requires_start": True,
        "rollback": {"available": False, "attempted": False},
    }


class SimulationDeploymentError(GarDomainError):
    def __init__(self, message: str, *, completed: Sequence[Artifact], failed: Artifact):
        self.details = {
            **placement_payload(completed),
            "placed": False,
            "partial": bool(completed),
            "failed_artifact": {"kind": failed.kind.value, "path": str(failed.bundle_path)},
            "failed_artifact_may_be_partial": True,
        }
        super().__init__(message)
