"""CLI execution boundary for application dispatch and access recovery."""

from __future__ import annotations

import sys

from scripts.gar_lib.application import dispatch
from scripts.gar_lib.commands.presentation import render_outcome
from scripts.gar_lib.commands.terminal import run_terminal_request
from scripts.gar_lib.composition import compose_application
from scripts.gar_lib.core.command import GarCommand
from scripts.gar_lib.core.errors import AccessConnectionError, GarDomainError
from scripts.gar_lib.recovery.access import AccessRecoveryPlanner
from scripts.gar_lib.recovery.terminal import TerminalBridgeRecoveryExecutor


def execute_application_command(
    command: GarCommand,
    *,
    workspace_selector: str | None,
    retry_command: str,
    json_output: bool = False,
    update_address: bool = True,
    update_repository: bool = False,
    manage_session: bool = True,
    settings: str | None = None,
    profile_name: str | None = None,
    params: dict[str, object] | None = None,
) -> int:
    services = compose_application()
    try:
        outcome = dispatch(
            command,
            workspace_selector=workspace_selector,
            services=services,
            update_address=update_address,
            update_repository=update_repository,
            manage_session=manage_session,
            settings=settings,
            profile_name=profile_name,
            params=params,
        )
        render_outcome(command, outcome, json_output=json_output)
        return outcome.exit_code
    except AccessConnectionError as exc:
        workspace = services.workspaces.get(workspace_selector)
        recovery = AccessRecoveryPlanner().plan(
            exc,
            workspace=workspace,
            retry_command=retry_command,
            purpose="target" if command.group == "target" else "simulation",
        )
        TerminalBridgeRecoveryExecutor(run_terminal_request).execute(recovery)
        print(f"gar: {exc}", file=sys.stderr)
        for instruction in recovery.instructions:
            print(f"  {instruction}", file=sys.stderr)
        return 1
    except GarDomainError as exc:
        print(f"gar: {exc}", file=sys.stderr)
        return 1
