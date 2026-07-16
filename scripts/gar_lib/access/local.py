"""Local background process access independent from simulator behavior."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ProcessLaunchResult:
    pid: int
    argv: tuple[str, ...]


class ProcessChannel(Protocol):
    def find_executable(self, name: str, *, candidates: tuple[Path, ...] = ()) -> str | None: ...

    def start(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        log_path: Path,
    ) -> ProcessLaunchResult: ...

    def is_running(self, pid: int) -> bool: ...

    def terminate_group(self, pid: int) -> None: ...


class LocalProcessChannel:
    def find_executable(self, name: str, *, candidates: tuple[Path, ...] = ()) -> str | None:
        executable = shutil.which(name)
        if executable:
            return executable
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        return None

    def start(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        log_path: Path,
    ) -> ProcessLaunchResult:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as log:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        return ProcessLaunchResult(process.pid, argv)

    def is_running(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def terminate_group(self, pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
