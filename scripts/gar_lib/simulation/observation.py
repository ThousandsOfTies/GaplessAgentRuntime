"""Observe host, transport, runtime and application without repairing them."""

from __future__ import annotations

from pathlib import Path

from scripts.gar_lib.artifacts.metadata import load_artifact_metadata, verify_artifact_checksums
from scripts.gar_lib.core.artifact import ArtifactKind
from scripts.gar_lib.core.errors import AccessConnectionError
from scripts.gar_lib.core.observation import EnvironmentObservation, component, unavailable
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.simulation.composition import HOSTLESS_SIMULATORS, simulation_environment_for, simulation_host_for


def observe_simulation(workspace: Workspace, hardware, *, diagnostic: bool, artifacts=None) -> EnvironmentObservation:
    backend = workspace.selected_environments.simulator
    parts: dict[str, dict[str, object]] = {}
    if backend in HOSTLESS_SIMULATORS:
        parts["host"] = unavailable("local process backend; managed hostなし")
    else:
        try:
            host = simulation_host_for(workspace).status()
            parts["host"] = component(host.state, host.running, backend=host.backend)
        except Exception as error:
            parts["host"] = component("error", False, error=str(error))
    try:
        environment = simulation_environment_for(workspace)
        observe = getattr(environment, "observe", None)
        if not callable(observe):
            raise ValueError(f"{backend} はruntimeの状態観測に未対応です")
        parts.update(observe(hardware, diagnostic=diagnostic))
    except Exception as error:
        for name in ("connection", "runtime", "app"):
            parts[name] = component("unknown", False, error=str(error))
        if isinstance(error, AccessConnectionError):
            parts["connection"] = component("unreachable", False, error=str(error), reason=error.reason)
    if artifacts is not None:
        app = parts["app"]
        expected = None
        try:
            artifact = artifacts.latest(ArtifactKind.SIM_APP, workspace)
            root = Path(artifact.bundle_path)
            metadata = load_artifact_metadata(root)
            if metadata is not None and not metadata.is_legacy:
                verify_artifact_checksums(root, metadata)
                expected = metadata.build_id
        except Exception as error:
            app["artifact_error"] = str(error)
        actual = app.get("running_build_id")
        match = bool(expected and actual and expected == actual)
        app.update(
            expected_build_id=expected,
            expected_source="latest_snapshot",
            build_id_match=match,
            build_id_verification="match" if match else "mismatch" if expected and actual else "unknown",
            ok=app.get("state") == "running" and match,
        )
        if app.get("state") in {"stopped", "not_deployed"}:
            app["build_id_verification"] = "stopped"
        if not match:
            app["reason"] = (
                "latest snapshotと起動時receiptのbuild ID一致を確認できません。sim deploy / sim start後に再確認してください。"
            )
    return EnvironmentObservation(f"sim.{'diag' if diagnostic else 'status'}", workspace.name, backend, parts)
