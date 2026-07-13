"""Simulation runtime interfaces independent from access mechanisms."""

from __future__ import annotations

from typing import Protocol

from scripts.gar_lib.core.artifact import Artifact
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.simulation.diagnostic import SimulationDiagnosticReport


class SimulationEnvironment(Protocol):
    @property
    def requires_runtime_artifact(self) -> bool: ...

    @property
    def runtime_host(self) -> str | None: ...

    def deploy(self, artifact: Artifact) -> None: ...

    def start(self, hardware: dict[str, list[dict[str, str]]]) -> int: ...

    def stop(self, hardware: dict[str, list[dict[str, str]]]) -> int: ...

    def status(self, hardware: dict[str, list[dict[str, str]]]) -> int: ...

    def diag(self, hardware: dict[str, list[dict[str, str]]]) -> SimulationDiagnosticReport: ...

    def log(self) -> int: ...


class SimulationEnvironmentResolver(Protocol):
    def for_workspace(self, workspace: Workspace) -> SimulationEnvironment: ...
