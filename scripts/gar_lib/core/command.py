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
TARGET_BUILD = GarCommand("target", "app", "build")
TARGET_DEPLOY = GarCommand("target", "app", "deploy")
