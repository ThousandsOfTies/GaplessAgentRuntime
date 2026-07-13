"""`gar shim`: deprecated alias for ``gar sim env build``."""

from __future__ import annotations

from scripts.gar_lib.commands.sim import run_sim_command
from scripts.gar_lib.core.command import SIM_RUNTIME_BUILD


def run_shim_command(command: str, *, json_output: bool = False) -> int:
    if command != "build":
        print(f"gar shim: unknown command: {command}")
        return 1

    del json_output
    return run_sim_command(
        SIM_RUNTIME_BUILD,
        workspace_selector=None,
        retry_command="gar shim build",
    )
