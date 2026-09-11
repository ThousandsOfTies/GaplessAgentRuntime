"""Common JSON envelope without discarding established command-specific fields."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from collections.abc import Callable

from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.observation import EnvironmentObservation
from scripts.gar_lib.core.output import JSON_OUTPUT, JSON_RESULT, emit_json


def render_observation(report: EnvironmentObservation, *, json_output: bool) -> int:
    payload = report.to_payload()
    if json_output:
        emit_json(payload)
    else:
        print(f"{report.command}: {report.workspace}")
        for name, value in report.components.items():
            print(f"  {name}: {value['state']}")
            if "expected_build_id" in value:
                print(
                    f"    build: {value.get('build_id_verification', 'unknown')} (expected={value.get('expected_build_id') or 'unknown'}, running={value.get('running_build_id') or 'unknown'})"
                )
            if detail := value.get("error") or value.get("reason"):
                print(f"    {detail}")
    return report.exit_code


def json_boundary(args: argparse.Namespace, run: Callable[[], int]) -> int:
    output, errors = io.StringIO(), io.StringIO()
    failure = None
    details = {}
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
        token = JSON_OUTPUT.set(True)
        result_token = JSON_RESULT.set(None)
        try:
            exit_code = run()
        except (GarDomainError, OSError, ValueError) as error:
            exit_code, failure = 1, str(error)
            details = getattr(error, "details", {})
        finally:
            structured = JSON_RESULT.get()
            JSON_RESULT.reset(result_token)
            JSON_OUTPUT.reset(token)
    text = output.getvalue().strip()
    payload = structured if structured is not None else {}
    if text:
        payload["output"] = text
    if failure:
        payload["error"] = failure
        payload.update(details)
    if errors.getvalue().strip():
        payload["diagnostics"] = errors.getvalue().strip()
        if payload.get("error"):
            payload["error"] = f"{payload['error']}: {payload['diagnostics']}"
    command = getattr(args, "gar_command", None)
    action = (
        command.action
        if command is not None
        else getattr(args, "code_command", None) or getattr(args, "infra_action", None)
    )
    if getattr(args, "capabilities", False):
        action = "capabilities"
    if "exit_code" in payload and payload["exit_code"] != exit_code:
        payload["backend_exit_code"] = payload["exit_code"]
    payload.update(schema_version=1, command=f"{args.command}.{action}", exit_code=exit_code)
    subject = command.subject if command is not None else getattr(args, "code_subject", None)
    if getattr(args, "sim_subject", None) == "infra":
        subject = "infra"
    if subject is not None:
        payload["subject"] = subject
    payload["ok"] = exit_code == 0 and payload.get("ok", True) is True
    workspace = getattr(args, "_gar_workspace", None)
    payload.setdefault("workspace", workspace.name if workspace is not None else getattr(args, "workspace", None))
    if not payload["ok"] and not payload.get("error") and structured is None:
        payload["error"] = payload.get("diagnostics") or f"command failed (exit {exit_code})"
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code
