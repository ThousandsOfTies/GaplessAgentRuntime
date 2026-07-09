"""`gar shim`: deprecated alias for ``gar sim env build``.

The implementation now lives in :mod:`scripts.gar_lib.commands.sim`
(``run_sim_env_build_command``). This module is kept only so the older
``gar shim build`` spelling keeps working.
"""

from __future__ import annotations

from scripts.gar_lib.commands.sim import run_sim_env_build_command


def run_shim_command(command: str, *, json_output: bool = False) -> int:
    if command != "build":
        print(f"gar shim: unknown command: {command}")
        return 1

    return run_sim_env_build_command(json_output=json_output)

