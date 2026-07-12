"""Build artifact model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from scripts.gar_lib.core.workspace import Workspace


class ArtifactKind(StrEnum):
    SIM_APP = "sim_app"
    SIM_RUNTIME = "sim_runtime"
    TARGET_APP = "target_app"


@dataclass(frozen=True)
class Artifact:
    kind: ArtifactKind
    workspace: Workspace
    bundle_path: Path
