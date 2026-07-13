"""ESP32 QEMU SimulationEnvironment component pending runtime implementation."""

from __future__ import annotations

from scripts.gar_lib.access.process import ProcessChannel
from scripts.gar_lib.simulation.pending import PendingSimulationEnvironment


class Esp32QemuSimulationEnvironment(PendingSimulationEnvironment):
    def __init__(self, process_channel: ProcessChannel):
        super().__init__("esp32_qemu_firmware", requires_runtime_artifact=False)
        self.process_channel = process_channel
