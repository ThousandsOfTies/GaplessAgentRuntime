"""NXP UUU process access without Target-specific artifact decisions."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from scripts.gar_lib.access.channel import AccessResult
from scripts.gar_lib.access.display import run_displayed
from scripts.gar_lib.core.errors import GarDomainError


class UuuCommandChannel(Protocol):
    def run(self, arguments: Sequence[str], *, cwd: Path) -> AccessResult: ...


class LocalUuuCommandChannel:
    """Invoke the host-native ``uuu``/``uuu.exe`` selected by ``PATH``."""

    def run(self, arguments: Sequence[str], *, cwd: Path) -> AccessResult:
        argv = tuple(arguments)
        try:
            completed = run_displayed(argv, cwd=cwd, runner=subprocess.run, check=False)
        except OSError as error:
            executable = argv[0] if argv else "uuu"
            raise GarDomainError(f"UUU commandを起動できません: {executable}: {error}") from error
        return AccessResult(argv, completed.returncode)
