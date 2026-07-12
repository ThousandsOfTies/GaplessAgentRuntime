"""Execute recovery actions that require a visible VS Code terminal."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Protocol

from scripts.gar_lib.recovery.access import RecoveryAction


class TerminalRequester(Protocol):
    def __call__(
        self,
        *,
        command_parts: list[str],
        command_text: str | None,
        title: str,
        cwd: str | None,
    ) -> int: ...


class TerminalBridgeRecoveryExecutor:
    def __init__(self, requester: TerminalRequester):
        self.requester = requester

    def execute(self, action: RecoveryAction) -> bool:
        if action.terminal_command is None:
            return False
        command = shlex.join(action.terminal_command)
        return (
            self.requester(
                command_parts=[],
                command_text=command,
                title=action.title,
                cwd=str(Path.cwd()),
            )
            == 0
        )
