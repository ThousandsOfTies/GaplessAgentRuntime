"""Explicit error-only SimulationEnvironment used while a runtime is being implemented."""

from __future__ import annotations

from typing import NoReturn

from scripts.gar_lib.core.artifact import Artifact
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.simulation.diagnostic import SimulationDiagnosticReport


class PendingSimulationEnvironment:
    """Keep a configured environment in the object graph without pretending it works."""

    runtime_host: str | None = None

    def __init__(
        self,
        environment_id: str,
        *,
        requires_runtime_artifact: bool,
    ):
        self.environment_id = environment_id
        self.requires_runtime_artifact = requires_runtime_artifact

    def deploy(self, artifact: Artifact) -> None:
        del artifact
        self._unsupported("deploy")

    def start(self, hardware: dict[str, list[dict[str, str]]]) -> int:
        del hardware
        self._unsupported("start")

    def stop(self, hardware: dict[str, list[dict[str, str]]]) -> int:
        del hardware
        self._unsupported("stop")

    def status(self, hardware: dict[str, list[dict[str, str]]]) -> int:
        del hardware
        self._unsupported("status")

    def diag(
        self,
        hardware: dict[str, list[dict[str, str]]],
    ) -> SimulationDiagnosticReport:
        del hardware
        self._unsupported("diag")

    def log(self) -> int:
        self._unsupported("log")

    def _unsupported(self, operation: str) -> NoReturn:
        raise GarDomainError(
            f"{self.environment_id} SimulationEnvironmentの{operation}はまだ実装されていません。"
        )
