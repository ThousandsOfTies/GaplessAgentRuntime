"""Structured simulation diagnostic results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from scripts.gar_lib.access.base import CommandResult
from scripts.gar_lib.simulation.parse import parse_sim_diag


class SimulationDiagnosticReport(Protocol):
    @property
    def exit_code(self) -> int: ...

    def to_payload(self, *, host: str | None = None) -> dict[str, object]: ...


@dataclass(frozen=True)
class PayloadSimulationDiagnostic:
    payload: Mapping[str, object]

    @property
    def exit_code(self) -> int:
        return 0 if self.payload.get("ok") is True else 1

    def to_payload(self, *, host: str | None = None) -> dict[str, object]:
        del host
        return dict(self.payload)


@dataclass(frozen=True)
class SimulationDiagnostic:
    processes: list[dict[str, object]]
    devices: dict[str, bool]
    api: Any | None
    ok: bool
    error: str | None = None
    stderr: str | None = None

    @classmethod
    def from_command(cls, result: CommandResult) -> SimulationDiagnostic:
        if result.returncode != 0:
            return cls(
                processes=[],
                devices={},
                api=None,
                ok=False,
                error=f"diagnostic command exited {result.returncode}",
                stderr=result.stderr.strip(),
            )

        payload = parse_sim_diag(result.stdout)
        return cls(
            processes=payload["processes"],
            devices=payload["devices"],
            api=payload["api"],
            ok=payload["ok"],
        )

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

    def to_payload(self, *, host: str | None = None) -> dict[str, object]:
        payload: dict[str, object] = {
            "processes": self.processes,
            "devices": self.devices,
            "api": self.api,
            "ok": self.ok,
        }
        if self.error is not None:
            payload["error"] = self.error
            payload["stderr"] = self.stderr or ""
        elif host:
            payload["host"] = host
        return payload
