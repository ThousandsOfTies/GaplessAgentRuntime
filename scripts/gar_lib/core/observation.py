"""Read-only observations with explicit scope and incomplete evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


def component(state: str, ok: bool | None, **details: object) -> dict[str, object]:
    return {"state": state, "ok": ok, **details}


def unavailable(reason: str) -> dict[str, object]:
    return component("not_applicable", None, reason=reason)


@dataclass(frozen=True)
class EnvironmentObservation:
    command: str
    workspace: str
    environment: str | None
    components: Mapping[str, Mapping[str, object]]

    @property
    def ok(self) -> bool:
        return all(
            value.get("ok") is True or value.get("state") == "not_applicable" for value in self.components.values()
        )

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "command": self.command,
            "workspace": self.workspace,
            "environment": self.environment,
            "ok": self.ok,
            "exit_code": self.exit_code,
            "components": {name: dict(value) for name, value in self.components.items()},
        }
