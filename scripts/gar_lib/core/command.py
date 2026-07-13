"""User intent represented independently from argparse and execution details."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GarCommand:
    group: str
    subject: str
    action: str


SIM_BUILD = GarCommand("sim", "app", "build")
SIM_CLEAN = GarCommand("sim", "app", "clean")
SIM_DEPLOY = GarCommand("sim", "app", "deploy")
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
TARGET_BUILD = GarCommand("target", "app", "build")
TARGET_DEPLOY = GarCommand("target", "app", "deploy")
