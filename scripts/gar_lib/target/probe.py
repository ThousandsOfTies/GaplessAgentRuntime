"""Bounded Product probe hooks, separate from deployment and lifecycle receipts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.gar_lib.core.errors import GarDomainError


def run_target_probe(workspace, name="status"):
    root = workspace.local_root.resolve()
    try:
        spec = json.loads((root / "gar-target-probe.json").read_text(encoding="utf-8"))
        if not isinstance(spec, dict) or not isinstance(spec.get("probes"), list):
            raise ValueError("expected descriptor with a probe list")
        relative = Path(spec["entrypoint"])
        entry = (root / relative).resolve()
        if (
            spec.get("schema_version") != 1
            or relative.is_absolute()
            or relative.drive
            or ".." in relative.parts
            or not entry.is_relative_to(root)
            or entry.suffix != ".py"
            or not entry.is_file()
            or not isinstance(name, str)
            or name not in spec["probes"]
        ):
            raise ValueError("invalid entrypoint or undeclared probe")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise GarDomainError(f"gar-target-probe.json: {error}") from error
    try:
        result = subprocess.run(
            [sys.executable, str(entry), name],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise GarDomainError("Target probe timed out (90 seconds)") from error
    try:
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError("expected JSON object")
    except ValueError as error:
        # Arbitrary hook output may contain credentials. Do not echo it on failure.
        raise GarDomainError(f"Target probe returned invalid JSON (exit {result.returncode})") from error
    payload.update(
        workspace=workspace.name,
        target_id=workspace.selected_target,
        probe=name,
        verification="probe_only",
        ok=result.returncode == 0 and payload.get("ok", True) is True,
    )
    return payload
