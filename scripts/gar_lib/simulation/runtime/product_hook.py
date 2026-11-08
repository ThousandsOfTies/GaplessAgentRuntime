"""Run a Product's existing simulator lifecycle through a bounded Python hook.

GAR retains checksum snapshots; the Product adapter owns its simulator protocol.
No terminal shell interprets the descriptor or its arguments.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.gar_lib.artifacts.metadata import load_artifact_metadata, verify_artifact_checksums
from scripts.gar_lib.core.artifact import ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.observation import component, unavailable


class ProductSimulatorHook:
    requires_runtime_artifact = False
    session_host = None

    def __init__(self, workspace, artifacts=None):
        self.workspace, self.artifacts = workspace, artifacts
        self.root = workspace.local_root.resolve()

    def _entry(self):
        try:
            spec = json.loads((self.root / "gar-simulator.json").read_text(encoding="utf-8"))
            relative = Path(spec["entrypoint"])
            if spec.get("schema_version") != 1 or relative.is_absolute() or relative.drive or ".." in relative.parts:
                raise ValueError("invalid descriptor")
            entry = self.root / relative
            if (
                entry.suffix != ".py"
                or not entry.is_file()
                or entry.is_symlink()
                or not entry.resolve().is_relative_to(self.root)
            ):
                raise ValueError("entrypoint must be a workspace Python file")
            return entry
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise GarDomainError(f"gar-simulator.json is invalid: {error}") from error

    def _run(self, action, *, artifact=None, captured=False):
        env = {**os.environ}
        if artifact is not None:
            metadata = load_artifact_metadata(artifact.bundle_path)
            if metadata is None or metadata.is_legacy:
                raise GarDomainError("A checksum snapshot is required; run gar sim build")
            verify_artifact_checksums(artifact.bundle_path, metadata)
            env.update(GAR_SIM_BUNDLE=str(artifact.bundle_path), GAR_SIM_BUILD_ID=metadata.build_id)
        result = subprocess.run(
            [sys.executable, str(self._entry()), action],
            cwd=self.root,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=captured,
            check=False,
        )
        if captured:
            if result.returncode:
                raise GarDomainError(f"Simulator {action} failed (exit {result.returncode}): {result.stderr[-2000:]}")
            try:
                value = json.loads(result.stdout)
                if not isinstance(value, dict):
                    raise ValueError("expected object")
                return value
            except ValueError as error:
                raise GarDomainError(f"Simulator {action} did not return JSON") from error
        if result.returncode:
            raise GarDomainError(f"Simulator {action} failed (exit {result.returncode})")
        return 0

    def build(self, kind, workspace):
        if kind is not ArtifactKind.SIM_APP:
            raise GarDomainError("product_hook packages application and simulator together")
        self._run("build")
        return self.artifacts.capture(kind, workspace)

    def fetch(self, kind, workspace):
        return self.artifacts.latest(kind, workspace)

    def clean(self, kind, workspace):
        raise GarDomainError("This hook does not declare a clean operation")

    def deploy(self, artifact):
        if artifact.kind is not ArtifactKind.SIM_APP:
            raise GarDomainError("product_hook requires a SIM_APP snapshot")
        self._run("deploy", artifact=artifact)

    def start(self, hardware):
        return self._run("start")

    def stop(self, hardware):
        return self._run("stop")

    def status(self, hardware):
        return self._run("status")

    def log(self):
        return self._run("log")

    def diag(self, hardware):
        from scripts.gar_lib.simulation.diagnostics.model import PayloadSimulationDiagnostic

        return PayloadSimulationDiagnostic(self._run("diag", captured=True))

    def observe(self, hardware, *, diagnostic):
        try:
            value = self._run("diag", captured=True)
            running = value.get("ok") is True
            return {
                "connection": component("reachable", True),
                "runtime": component("ready" if running else "unhealthy", running, evidence=value),
                "app": component(
                    "running" if running else "stopped",
                    running,
                    running_build_id=value.get("runningBuildId"),
                    deployed_build_id=value.get("deployedBuildId"),
                ),
            }
        except Exception as error:
            return {
                "connection": component("error", False, error=str(error)),
                "runtime": unavailable("simulator diagnostic unavailable"),
                "app": component("unknown", False),
            }
