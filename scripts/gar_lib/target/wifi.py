"""Run Product-bound interactive OS configuration recipes."""

import json
import subprocess
import sys
from pathlib import Path

from scripts.gar_lib.core.errors import GarDomainError


def configure_wifi(workspace, transport="ssh", check=False, repair_host=None):
    return _configure(workspace, "gar-target-wifi.json", transport, check, repair_host)


def configure_audio(workspace):
    return _configure(workspace, "gar-target-audio.json", "ssh", False, None)


def trace_conversation(workspace):
    return _configure(workspace, "gar-target-trace.json", "ssh", False, None)


def update_runtime(workspace, phase):
    if phase not in ("build", "preflight", "deploy", "diag"):
        raise GarDomainError("Invalid runtime update phase")
    return _configure(workspace, "gar-target-update.json", "ssh", False, None, ("--phase", phase))


def _configure(workspace, descriptor, transport, check, repair_host, extra_arguments=()):
    if transport not in ("serial", "ssh"):
        raise GarDomainError("Unsupported Wi-Fi setup transport")
    if check and transport != "ssh":
        raise GarDomainError("Read-only Wi-Fi checks require --transport ssh")
    root = workspace.local_root.resolve()
    try:
        spec = json.loads((root / descriptor).read_text(encoding="utf-8"))
        relative = Path(spec["entrypoint"])
        entry = (root / relative).resolve()
        if (
            spec.get("schema_version") != 1
            or relative.is_absolute()
            or relative.drive
            or ".." in relative.parts
            or not entry.is_relative_to(root)
            or not entry.is_file()
            or entry.suffix != ".py"
        ):
            raise ValueError("invalid entrypoint")
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise GarDomainError(f"Invalid {descriptor} descriptor") from error
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(entry),
                "--transport",
                transport,
                *(["--check"] if check else []),
                *(["--repair-host", repair_host] if repair_host else []),
                *extra_arguments,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
            check=False,
        )
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise ValueError("expected object")
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        # Never echo a provisioning command, credential or arbitrary child output.
        raise GarDomainError("Wi-Fi setup did not return a valid result") from error
    report = {
        key: value[key]
        for key in (
            "ok",
            "state",
            "address",
            "interface",
            "internet",
            "reconnected",
            "usbManagementOnly",
            "error",
            "preflight",
            "saved",
            "restoreVerified",
            "hotplugRule",
            "card",
            "playbackPercent",
            "trace",
            "deployment",
        )
        if key in value
    }
    report.update(
        workspace=workspace.name,
        target_id=workspace.selected_target,
        ok=result.returncode == 0 and value.get("ok") is True,
    )
    return report
