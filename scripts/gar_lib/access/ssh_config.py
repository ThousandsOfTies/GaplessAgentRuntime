"""Update SSH host aliases independently from host lifecycle control."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol


class HostAddressUpdater(Protocol):
    def update(self, host: str, address: str) -> bool: ...


class SshConfigHostAddressUpdater:
    def __init__(self, path: Path | None = None):
        self.path = path or Path.home() / ".ssh" / "config"

    def update(self, host: str, address: str) -> bool:
        if not self.path.exists():
            return False

        lines = self.path.read_text(encoding="utf-8").splitlines()
        host_pattern = re.compile(r"^\s*Host\s+(.+?)\s*$", re.IGNORECASE)
        hostname_pattern = re.compile(r"^(\s*)HostName\s+\S+\s*$", re.IGNORECASE)

        target_start: int | None = None
        target_end = len(lines)
        for index, line in enumerate(lines):
            host_match = host_pattern.match(line)
            if not host_match:
                continue
            if target_start is not None:
                target_end = index
                break
            if host in host_match.group(1).split():
                target_start = index

        if target_start is None:
            return False

        for index in range(target_start + 1, target_end):
            hostname_match = hostname_pattern.match(lines[index])
            if hostname_match:
                indent = hostname_match.group(1) or "    "
                lines[index] = f"{indent}HostName {address}"
                self._write(lines)
                return True

        lines.insert(target_start + 1, f"    HostName {address}")
        self._write(lines)
        return True

    def _write(self, lines: list[str]) -> None:
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
