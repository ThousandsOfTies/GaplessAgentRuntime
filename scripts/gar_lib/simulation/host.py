"""Simulation host lifecycle interfaces and results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from scripts.gar_lib.core.workspace import Workspace


@dataclass(frozen=True)
class SimulationHostState:
    host: str
    instance_id: str
    region: str
    state: str
    public_ip: str | None

    @property
    def running(self) -> bool:
        return self.state == "running"

    def to_payload(self) -> dict[str, object]:
        return {
            "command": "sim status",
            "instance_id": self.instance_id,
            "region": self.region,
            "state": self.state,
            "public_ip": self.public_ip,
            "running": self.running,
            "ok": True,
        }


@dataclass(frozen=True)
class SimulationHostStartResult:
    state: SimulationHostState
    address_updated: bool
    repository_updated: bool
    repository_update_skipped: bool


class SimulationHostController(Protocol):
    def start(
        self,
        *,
        update_address: bool = True,
        update_repository: bool = False,
    ) -> SimulationHostStartResult: ...

    def stop(self) -> None: ...

    def status(self) -> SimulationHostState: ...


class SimulationHostControllerResolver(Protocol):
    def for_workspace(self, workspace: Workspace) -> SimulationHostController: ...
