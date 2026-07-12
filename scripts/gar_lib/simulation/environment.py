"""Simulation runtime interfaces independent from access mechanisms."""

from __future__ import annotations

from typing import Protocol

from scripts.gar_lib.core.artifact import Artifact


class DeployableSimulationEnvironment(Protocol):
    def deploy(self, artifact: Artifact) -> None: ...


class SimulationEnvironmentResolver(Protocol):
    def for_workspace(self, workspace: object) -> DeployableSimulationEnvironment: ...
