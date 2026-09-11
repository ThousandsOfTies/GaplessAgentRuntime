"""Local MuJoCo simulation runtime environment."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

from scripts.gar_lib.artifacts.manifest import load_deploy_files, resolve_artifact_src
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.config import PROJECT_ROOT
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.observation import component, unavailable
from scripts.gar_lib.simulation.diagnostics.model import PayloadSimulationDiagnostic
from scripts.gar_lib.simulation.hardware.mujoco import DEFAULT_BRIDGE_URL, bridge_state
from scripts.gar_lib.simulation.runtime.deployment import deployment_record
from scripts.gar_lib.simulation.runtime.local_identity import LocalApplicationIdentity
from scripts.gar_lib.simulation.runtime.process import (
    LocalProcessChannel,
    ManagedProcess,
    ProcessChannel,
    ProcessStateStore,
)

DEFAULT_MODEL_PATH = PROJECT_ROOT / "examples" / "mujoco" / "pendulum.xml"
DEFAULT_WORKSPACE_DIR = PROJECT_ROOT / ".gar" / "mujoco"


class MujocoSimulationEnvironment:
    """Manage a local MuJoCo runner through the SimulationEnvironment contract."""

    requires_runtime_artifact = False
    session_host: str | None = None

    def __init__(
        self,
        workspace_dir: Path | None = None,
        process_channel: ProcessChannel | None = None,
    ):
        configured = os.environ.get("GAR_MUJOCO_WORKSPACE")
        selected_dir = workspace_dir or Path(configured or DEFAULT_WORKSPACE_DIR)
        self.workspace_dir = Path(os.path.abspath(selected_dir.expanduser()))
        self.process_channel = process_channel or LocalProcessChannel()
        self.state_path = self.workspace_dir / "state.json"
        self.state_store = ProcessStateStore(self.state_path)
        self.log_path = self.workspace_dir / "mujoco.log"
        self.identity = LocalApplicationIdentity(self.workspace_dir)

    def deploy(self, artifact: Artifact) -> None:
        with self.state_store.locked():
            self._deploy(artifact)

    def _deploy(self, artifact: Artifact) -> None:
        if artifact.kind is not ArtifactKind.SIM_APP:
            raise GarDomainError(f"MuJoCoへ配置できないartifactです: {artifact.kind.value}")
        loaded = load_deploy_files(artifact.bundle_path, "app")
        if loaded is None:
            raise GarDomainError(f"MuJoCo artifact manifestを読み込めません: {artifact.bundle_path}")
        bundle_root, files = loaded
        receipt = deployment_record(bundle_root, files, self._workspace_destination)
        self.identity.begin(receipt)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        for entry in files:
            source = resolve_artifact_src(bundle_root, entry["src"])
            if source is None:
                raise GarDomainError(f"MuJoCo artifact sourceがありません: {entry['src']}")
            destination = self._workspace_destination(entry["dest"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(source, destination)
            mode = entry.get("mode")
            if isinstance(mode, str):
                destination.chmod(int(mode, 8))
        self._validate_model_or_raise()
        self.identity.finish(receipt)

    def start(self, hardware: dict[str, list[dict[str, str]]]) -> int:
        del hardware
        with self.state_store.locked():
            current_process = ManagedProcess.from_state(self._state())
            if current_process is not None and self.process_channel.owns(current_process):
                self._print_status("running", True, pid=current_process.pid)
                return 0

            self._validate_model_or_raise()
            runner = self._runner_path()
            if runner is not None and not runner.is_file():
                raise GarDomainError(f"MuJoCo runnerが見つかりません: {runner}")

            required = (self._model_path(),) + ((runner,) if runner else ())
            before = self.identity.capture(required)
            launch_dir = self.identity.stage(before, self.workspace_dir)
            model = self._model_path()
            if launch_dir is not None:
                model = launch_dir / model.relative_to(self.workspace_dir.resolve())
                if runner:
                    runner = launch_dir / runner.relative_to(self.workspace_dir.resolve())
            else:
                before = {}
            if runner:
                command = (
                    sys.executable,
                    str(runner),
                    "--mjcf",
                    str(model),
                    "--bridge-url",
                    self._bridge_url(),
                )
            else:
                bridge = urllib.parse.urlparse(self._bridge_url())
                if bridge.scheme != "http" or bridge.hostname is None:
                    raise GarDomainError("GAR_MUJOCO_BRIDGE_URLはhttp://host:portで指定してください。")
                command = (
                    sys.executable,
                    str(PROJECT_ROOT / "examples" / "mujoco" / "bridge.py"),
                    "--mjcf",
                    str(model),
                    "--host",
                    bridge.hostname,
                    "--port",
                    str(bridge.port or 80),
                    "--viewer",
                )

            launched = self.process_channel.start(
                command,
                cwd=PROJECT_ROOT,
                log_path=self.log_path,
            )
            try:
                self._write_state(
                    {
                        **launched.to_state(),
                        "bridge_url": self._bridge_url(),
                        "app_build": self.identity.launched(before, required),
                    }
                )
            except Exception:
                self.process_channel.terminate_group(launched)
                raise
        self._print_status("running", True, pid=launched.pid)
        return 0

    def stop(self, hardware: dict[str, list[dict[str, str]]]) -> int:
        del hardware
        with self.state_store.locked():
            process = ManagedProcess.from_state(self._state())
            if process is not None:
                self.process_channel.terminate_group(process)
            self._write_state({})
        self._print_status("stopped", True)
        return 0

    def status(self, hardware: dict[str, list[dict[str, str]]]) -> int:
        diagnostic = self.diag(hardware)
        payload = diagnostic.to_payload()
        self._print_status(
            str(payload.get("status", "unknown")),
            payload.get("ok") is True,
            pid=payload.get("pid"),
        )
        return diagnostic.exit_code

    def diag(
        self,
        hardware: dict[str, list[dict[str, str]]],
    ) -> PayloadSimulationDiagnostic:
        del hardware
        model_ok, model_error = self._validate_model()
        state = self._state()
        process = ManagedProcess.from_state(state)
        running = process is not None and self.process_channel.owns(process)
        current_bridge_state = bridge_state(self._bridge_url()) if running else None
        ok = model_ok and running and current_bridge_state is not None
        return PayloadSimulationDiagnostic(
            {
                "environment": "mujoco",
                "status": "running" if ok else ("degraded" if running else "stopped"),
                "ok": ok,
                "model": str(self._model_path()),
                "runner": str(self._runner_path()) if self._runner_path() else None,
                "bridge_url": self._bridge_url(),
                "pid": process.pid if running and process is not None else None,
                "bridge_state": current_bridge_state,
                **({"error": model_error} if model_error else {}),
            }
        )

    def log(self) -> int:
        if not self.log_path.exists():
            raise GarDomainError(f"MuJoCo logが見つかりません: {self.log_path}")
        print(self.log_path.read_text(encoding="utf-8"), end="")
        return 0

    def observe(self, hardware, *, diagnostic: bool) -> dict[str, dict[str, object]]:
        state = self._state()
        process = ManagedProcess.from_state(state)
        running = process is not None and self.process_channel.owns(process)
        app_identity = self.identity.observe(state, self.process_channel)
        runtime = component("running" if running else "stopped", running)
        if diagnostic:
            report = self.diag(hardware)
            runtime["diagnostic"] = report.to_payload()
            runtime["ok"] = running and report.exit_code == 0
            if running and not runtime["ok"]:
                runtime["state"] = "degraded"
        return {
            "connection": unavailable("local process; remote connectionなし"),
            "runtime": runtime,
            "app": component(
                "running" if running else "stopped",
                running and app_identity["build_id_match"],
                **app_identity,
            ),
        }

    def _model_path(self) -> Path:
        return Path(os.environ.get("GAR_MUJOCO_MODEL", DEFAULT_MODEL_PATH)).expanduser().resolve()

    def _runner_path(self) -> Path | None:
        value = os.environ.get("GAR_MUJOCO_RUNNER")
        return Path(value).expanduser().resolve() if value else None

    def _bridge_url(self) -> str:
        return os.environ.get("GAR_MUJOCO_BRIDGE_URL", DEFAULT_BRIDGE_URL).rstrip("/")

    def _workspace_destination(self, value: str) -> Path:
        destination = Path(value)
        if destination.is_absolute() or value.startswith("~") or ".." in destination.parts:
            raise GarDomainError(f"MuJoCo artifactのdestはworkspace相対pathで指定してください: {value}")
        return self.workspace_dir / destination

    def _state(self) -> dict[str, object]:
        return self.state_store.read()

    def _write_state(self, state: dict[str, object]) -> None:
        self.state_store.write(state)

    def _validate_model(self) -> tuple[bool, str | None]:
        model = self._model_path()
        if not model.is_file():
            return False, f"MJCF/URDF modelが見つかりません: {model}"
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import mujoco, sys; mujoco.MjModel.from_xml_path(sys.argv[1])",
                str(model),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            return False, (result.stderr or result.stdout).strip() or "MuJoCoがmodelを読み込めません"
        return True, None

    def _validate_model_or_raise(self) -> None:
        ok, error = self._validate_model()
        if not ok:
            raise GarDomainError(error or "MuJoCo modelが無効です。")

    @staticmethod
    def _print_status(status: str, ok: bool, *, pid: object = None) -> None:
        print("environment: mujoco")
        print(f"status: {status}")
        print(f"ok: {str(ok).lower()}")
        if pid is not None:
            print(f"pid: {pid}")
