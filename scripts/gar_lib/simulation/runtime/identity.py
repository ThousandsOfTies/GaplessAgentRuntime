"""Process-bound simulation receipts. This module also runs on a Linux Sim Host.

Keep this file standard-library-only: its source is sent through CommandChannel.
A receipt proves the inputs at GAR start, not application-level health.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

DEPLOYED = Path("/var/lib/gar/simulation/app-deployed.json")
RUNNING = Path("/run/gar/app-running.json")
SERVICE = "gar-sim-app.service"


def read_record(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) and value.get("schema_version") == 1 else {}
    except (OSError, ValueError):
        return {}


def write_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".receipt-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({**record, "schema_version": 1}, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def verified(record: dict, required: tuple[Path, ...] = ()) -> bool:
    files = record.get("files")
    if record.get("state") != "ready" or not record.get("build_id") or not isinstance(files, dict) or not files:
        return False
    if any(str(path) not in files for path in required):
        return False
    try:
        return all(Path(name).is_absolute() and digest(Path(name)) == expected for name, expected in files.items())
    except (OSError, TypeError, ValueError):
        return False


def launch_build(record: dict, current: dict, required: tuple[Path, ...] = ()) -> dict:
    if record != current or not verified(current, required):
        return {}
    return {"build_id": record["build_id"], "generation": record.get("generation")}


def observation(deployed: dict, launched: dict, *, running: bool) -> dict:
    expected = deployed.get("build_id") if deployed.get("state") == "ready" else None
    actual = launched.get("build_id") if running else None
    match = bool(expected and actual and expected == actual)
    state = "match" if match else "mismatch" if expected and actual else "unknown"
    if not running:
        state = "stopped"
    return {
        "expected_build_id": expected,
        "deployed_build_id": expected,
        "running_build_id": actual,
        "build_id_match": match,
        "build_id_verification": state,
        "verification": "launch_receipt",
    }


def process_ticks(pid: int) -> int | None:
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def service_state(service: str) -> dict:
    probe = subprocess.run(
        ["systemctl", "show", service, "--property=LoadState,ActiveState,ExecStart,MainPID,InvocationID"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    fields = dict(line.split("=", 1) for line in probe.stdout.splitlines() if "=" in line)
    try:
        pid = int(fields.get("MainPID", "0"))
    except ValueError:
        pid = 0
    return {
        "loaded": fields.get("LoadState") == "loaded",
        "active": fields.get("ActiveState") == "active",
        "placeholder": service == SERVICE and "path=/bin/true" in fields.get("ExecStart", ""),
        "exit_code": probe.returncode,
        "pid": pid,
        "start_time_ticks": process_ticks(pid) if pid > 0 else None,
        "invocation_id": fields.get("InvocationID", ""),
    }


def service_identity(state: dict) -> dict:
    return {key: state.get(key) for key in ("pid", "start_time_ticks", "invocation_id")}


def service_running(state: dict) -> bool:
    return (
        state.get("active") is True
        and state.get("loaded") is True
        and not state.get("placeholder")
        and state.get("exit_code") == 0
    )


def process_uses_artifact(record: dict, pid: int) -> bool:
    """Require the actual executable or script argument to belong to the snapshot."""
    files = record.get("files", {})
    try:
        executable = Path(f"/proc/{pid}/exe")
        target = str(executable.readlink()).removesuffix(" (deleted)")
        if target in files and digest(executable) == files[target]:
            return True
        arguments = Path(f"/proc/{pid}/cmdline").read_bytes().decode().rstrip("\0").split("\0")
        cwd = Path(f"/proc/{pid}/cwd").readlink()
        for argument in arguments[1:]:
            path = Path(argument)
            if not path.is_absolute():
                path = cwd / path
            name = str(path)
            if name == record.get("entrypoint") and name in files and digest(path) == files[name]:
                return True
    except (OSError, ValueError, UnicodeError):
        pass
    return False


def observe_service(state: dict, deployed: Path = DEPLOYED, running_path: Path = RUNNING) -> dict:
    launched = read_record(running_path)
    identity = service_identity(state)
    if not all(identity.values()) or identity != launched.get("process"):
        launched = {}
    return observation(read_record(deployed), launched, running=service_running(state))


def start_service(command: str, deployed: Path = DEPLOYED, running_path: Path = RUNNING) -> int:
    before = read_record(deployed)
    eligible = verified(before)
    # An interrupted or failed start must never retain a previous attestation.
    write_record(running_path, {})
    user = os.environ.get("SUDO_USER")
    # Preserve the original user's home expansion in legacy runtime installation.
    prefix = ["sudo", "-H", "-u", user] if user and user != "root" else []
    result = subprocess.call([*prefix, "sh", "-c", command])
    if result == 0 and eligible:
        state = service_state(SERVICE)
        identity = service_identity(state)
        build = launch_build(before, read_record(deployed))
        if build and service_running(state) and all(identity.values()) and process_uses_artifact(before, state["pid"]):
            write_record(running_path, {**build, "process": identity})
    return result
