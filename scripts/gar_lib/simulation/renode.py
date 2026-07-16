"""Renode SimulationEnvironment component pending runtime implementation."""

from __future__ import annotations

from scripts.gar_lib.access.local import ProcessChannel
from scripts.gar_lib.simulation.pending import PendingSimulationEnvironment


class RenodeSimulationEnvironment(PendingSimulationEnvironment):
    def __init__(self, process_channel: ProcessChannel):
        super().__init__("renode_mcu", requires_runtime_artifact=False)
        self.process_channel = process_channel
