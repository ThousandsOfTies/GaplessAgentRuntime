"""Wokwi simulation provider.

This is a minimal provider hook so `gar setup` can select Wokwi as the
simulation connection target. Runtime operations are currently noops in
`scripts.gar_lib.sim.wokwi`.
"""

from __future__ import annotations

from scripts.gar_lib.environments.base import DevEnvironment


class WokwiEnvironment(DevEnvironment):
    provider_id = "wokwi"
    display_name = "Wokwi"
    description = "ESP32 firmware simulation backend via Wokwi CLI/CI（現時点はnoop接続先）"
    display_order = 16
    required_commands = ()

    @classmethod
    def list_instances(cls) -> int:
        print("target: Wokwi project directory / firmware artifact")
        print("status: noop provider hook")
        return 0

    @classmethod
    def shell(cls, target: str | None = None) -> int:
        print("Wokwi simulation provider is configured. Runtime execution is not implemented yet.")
        return 0

    @classmethod
    def start_port_forward(cls, target: str) -> int:
        return 0

    @classmethod
    def stop_port_forward(cls, target: str) -> int:
        return 0

    @classmethod
    def status_port_forward(cls, target: str) -> int:
        return 0

    @classmethod
    def interactive_shell_script(cls, target: str) -> str:
        return """#!/usr/bin/env bash
set -euo pipefail

echo "Wokwi simulation provider is configured."
echo "Runtime execution is not implemented yet."
"""
