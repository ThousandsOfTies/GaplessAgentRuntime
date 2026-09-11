"""Identity bookkeeping shared by local simulator processes."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from scripts.gar_lib.simulation.runtime import identity
from scripts.gar_lib.simulation.runtime.process import ManagedProcess, ProcessChannel


class LocalApplicationIdentity:
    def __init__(self, project: Path):
        # Keep receipts outside the artifact's writable deployment tree.
        project = Path(os.path.abspath(project.expanduser()))
        self.path = project.with_name(project.name + ".identity") / "deployed.json"

    def begin(self, record: dict) -> None:
        identity.write_record(self.path, {**record, "state": "deploying"})

    def finish(self, record: dict) -> None:
        if record.get("build_id") and not identity.verified(record):
            raise ValueError("deployed app checksum mismatch")
        identity.write_record(self.path, record)

    def capture(self, required: tuple[Path, ...]) -> dict:
        record = identity.read_record(self.path)
        return record if identity.verified(record, required) else {}

    def launched(self, before: dict, required: tuple[Path, ...]) -> dict:
        return identity.launch_build(before, identity.read_record(self.path), required)

    def stage(self, record: dict, project: Path) -> Path | None:
        """Pin launch inputs so a later deploy cannot change an asynchronously loaded model/firmware."""
        if not record:
            return None
        project = project.resolve()
        files = {Path(name): expected for name, expected in record["files"].items()}
        if any(not path.is_relative_to(project) for path in files):
            return None
        directory = self.path.parent / "runs"
        directory.mkdir(parents=True, exist_ok=True)
        launch = Path(tempfile.mkdtemp(prefix="app-", dir=directory))
        try:
            for source, expected in files.items():
                destination = launch / source.relative_to(project)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                if identity.digest(destination) != expected:
                    raise ValueError("launch input checksum mismatch")
            return launch
        except Exception:
            shutil.rmtree(launch)
            raise

    def observe(self, state: dict, channel: ProcessChannel) -> dict:
        process = ManagedProcess.from_state(state)
        running = state.get("status") != "stopped" and process is not None and channel.owns(process)
        build = state.get("app_build", {}) if process is not None and process.start_time_ticks is not None else {}
        return identity.observation(
            identity.read_record(self.path), build if isinstance(build, dict) else {}, running=running
        )
