"""User-visible session integration for a simulation runtime."""

from __future__ import annotations

from typing import Protocol

from scripts.gar_lib.simulation.remote_session import (
    start_sim_port_forward,
    status_sim_port_forward,
    stop_sim_port_forward,
    write_sim_terminal_profile,
)


class SimulationSessionManager(Protocol):
    def configure_terminal(
        self,
        host: str,
        *,
        settings: str | None,
        profile_name: str | None,
    ) -> None: ...

    def start(self, host: str) -> int: ...

    def stop(self, host: str) -> int: ...

    def status(self, host: str) -> int: ...


class VsCodeSimulationSessionManager:
    def configure_terminal(
        self,
        host: str,
        *,
        settings: str | None,
        profile_name: str | None,
    ) -> None:
        write_sim_terminal_profile(host=host, settings=settings, profile_name=profile_name)

    def start(self, host: str) -> int:
        return start_sim_port_forward(host)

    def stop(self, host: str) -> int:
        return stop_sim_port_forward(host)

    def status(self, host: str) -> int:
        return status_sim_port_forward(host)
