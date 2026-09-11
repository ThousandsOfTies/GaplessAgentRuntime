"""User intent represented independently from argparse and execution details."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from scripts.gar_lib.core.command_surface import action_first


@dataclass(frozen=True)
class GarCommand:
    """A GAR CLI command path independent from argparse."""

    group: str
    subject: str | None
    action: str

    def to_cli(self, *, workspace: str | None = None, options: Sequence[str] = ()) -> str:
        """このcommandを再実行するCLI文字列。retry案内はすべてここから生成する。"""
        parts = ["gar", self.group]
        if action_first(self.group, self.action, self.subject):
            parts.append(self.action)
            if self.subject:
                parts.append(self.subject)
        else:
            if self.subject:
                parts.append(self.subject)
            parts.append(self.action)
        parts.extend(options)
        if workspace:
            parts.extend(("--workspace", workspace))
        return " ".join(parts)


SIM_APP_BUILD = GarCommand("sim", "app", "build")
SIM_APP_CLEAN = GarCommand("sim", "app", "clean")
SIM_APP_DEPLOY = GarCommand("sim", "app", "deploy")
SIM_RUNTIME_BUILD = GarCommand("sim", "runtime", "build")
SIM_RUNTIME_DEPLOY = GarCommand("sim", "runtime", "deploy")
SIM_RUNTIME_START = GarCommand("sim", "runtime", "start")
SIM_RUNTIME_STOP = GarCommand("sim", "runtime", "stop")
SIM_RUNTIME_STATUS = GarCommand("sim", "runtime", "status")
SIM_RUNTIME_LOG = GarCommand("sim", "runtime", "log")
SIM_RUNTIME_DIAG = GarCommand("sim", "runtime", "diag")
SIM_HOST_START = GarCommand("sim", "host", "start")
SIM_HOST_STOP = GarCommand("sim", "host", "stop")
SIM_HOST_STATUS = GarCommand("sim", "host", "status")
TARGET_BUILD = GarCommand("target", None, "build")
TARGET_DEPLOY = GarCommand("target", None, "deploy")
TARGET_FETCH = GarCommand("target", None, "fetch")
