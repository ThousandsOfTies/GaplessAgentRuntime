"""CLI boundary for ``gar hw``."""

from __future__ import annotations

from scripts.gar_lib.hardware import write_hw_template


def run_hw_command(command: str, *, output_dir: str | None = None, force: bool = False) -> int:
    if command == "init":
        return write_hw_template(output_dir=output_dir, force=force)

    print(f"gar hw: unknown command: {command}")
    return 1
