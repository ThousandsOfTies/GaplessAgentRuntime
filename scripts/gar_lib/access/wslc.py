"""Windows WSL Containers CLI discovery and execution."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from scripts.gar_lib.access.channel import AccessResult, run_cli
from scripts.gar_lib.core.errors import GarDomainError


def find_wslc() -> str | None:
    executable = shutil.which("wslc")
    if executable is not None:
        return executable
    if os.name == "nt":
        # Existing terminals may retain their pre-update PATH.
        installed = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WSL" / "wslc.exe"
        if installed.is_file():
            return str(installed)
    return None


class WslcCliChannel:
    def run(self, arguments: tuple[str, ...]) -> AccessResult:
        executable = find_wslc()
        if executable is None:
            raise GarDomainError("wslc が見つかりません。Windows で wsl --update を実行してください。")
        return run_cli((executable, *arguments), runner=subprocess.run, encoding="utf-8")
