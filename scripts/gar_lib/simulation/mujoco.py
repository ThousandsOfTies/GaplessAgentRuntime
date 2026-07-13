"""Local MuJoCo simulation and bridge control environments."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from scripts.gar_lib.access.process import LocalProcessChannel, ProcessChannel
from scripts.gar_lib.config import PROJECT_ROOT
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.simulation.control import HardwareControlResult
from scripts.gar_lib.simulation.diagnostic import PayloadSimulationDiagnostic

DEFAULT_MODEL_PATH = PROJECT_ROOT / "examples" / "mujoco" / "pendulum.xml"
DEFAULT_WORKSPACE_DIR = PROJECT_ROOT / ".gar" / "mujoco"
DEFAULT_BRIDGE_URL = "http://127.0.0.1:8081"


class MujocoSimulationEnvironment:
    """Manage a local MuJoCo runner through the SimulationEnvironment contract."""

    requires_runtime_artifact = False
    runtime_host: str | None = None

    def __init__(
        self,
        workspace_dir: Path | None = None,
        process_channel: ProcessChannel | None = None,
    ):
        configured = os.environ.get("GAR_MUJOCO_WORKSPACE")
        self.workspace_dir = workspace_dir or Path(
            configured or DEFAULT_WORKSPACE_DIR
        ).expanduser().resolve()
        self.process_channel = process_channel or LocalProcessChannel()
        self.state_path = self.workspace_dir / "state.json"
        self.log_path = self.workspace_dir / "mujoco.log"

    def deploy(self, artifact: Artifact) -> None:
        if artifact.kind is not ArtifactKind.SIM_APP:
            raise GarDomainError(f"MuJoCoへ配置できないartifactです: {artifact.kind.value}")
        self._validate_model_or_raise()

    def start(self, hardware: dict[str, list[dict[str, str]]]) -> int:
        del hardware
        self._validate_model_or_raise()
        runner = self._runner_path()
        if runner is not None and not runner.is_file():
            raise GarDomainError(f"MuJoCo runnerが見つかりません: {runner}")

        if runner:
            command = (
                sys.executable,
                str(runner),
                "--mjcf",
                str(self._model_path()),
                "--bridge-url",
                self._bridge_url(),
            )
        else:
            bridge = urllib.parse.urlparse(self._bridge_url())
            if bridge.scheme != "http" or bridge.hostname is None:
                raise GarDomainError("GAR_MUJOCO_BRIDGE_URLはhttp://host:portで指定してください。")
            command = (
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "mujoco_bridge.py"),
                "--mjcf",
                str(self._model_path()),
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
        self._write_state(
            {"pid": launched.pid, "command": list(command), "bridge_url": self._bridge_url()}
        )
        self._print_status("running", True, pid=launched.pid)
        return 0

    def stop(self, hardware: dict[str, list[dict[str, str]]]) -> int:
        del hardware
        pid = self._state().get("pid")
        if isinstance(pid, int):
            self.process_channel.terminate_group(pid)
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
        pid = state.get("pid")
        running = isinstance(pid, int) and self.process_channel.is_running(pid)
        bridge_state = _bridge_state(self._bridge_url()) if running else None
        ok = model_ok and running and bridge_state is not None
        return PayloadSimulationDiagnostic(
            {
                "environment": "mujoco",
                "status": "running" if ok else ("degraded" if running else "stopped"),
                "ok": ok,
                "model": str(self._model_path()),
                "runner": str(self._runner_path()) if self._runner_path() else None,
                "bridge_url": self._bridge_url(),
                "pid": pid if running else None,
                "bridge_state": bridge_state,
                **({"error": model_error} if model_error else {}),
            }
        )

    def log(self) -> int:
        if not self.log_path.exists():
            raise GarDomainError(f"MuJoCo logが見つかりません: {self.log_path}")
        print(self.log_path.read_text(encoding="utf-8"), end="")
        return 0

    def _model_path(self) -> Path:
        return Path(os.environ.get("GAR_MUJOCO_MODEL", DEFAULT_MODEL_PATH)).expanduser().resolve()

    def _runner_path(self) -> Path | None:
        value = os.environ.get("GAR_MUJOCO_RUNNER")
        return Path(value).expanduser().resolve() if value else None

    def _bridge_url(self) -> str:
        return os.environ.get("GAR_MUJOCO_BRIDGE_URL", DEFAULT_BRIDGE_URL).rstrip("/")

    def _state(self) -> dict[str, object]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_state(self, state: dict[str, object]) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

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


class MujocoBridgeHardwareControl:
    """Translate common control-plane operations to the MuJoCo JSON bridge."""

    def __init__(self, bridge_url: str | None = None):
        self.bridge_url = (bridge_url or os.environ.get("GAR_MUJOCO_BRIDGE_URL", DEFAULT_BRIDGE_URL)).rstrip("/")

    def gpio(
        self,
        action: str,
        hardware: dict[str, list[dict[str, str]]],
    ) -> HardwareControlResult:
        del hardware
        return HardwareControlResult(
            0,
            {
                "environment": "mujoco",
                "action": action,
                "ok": True,
                "status": "not-applicable",
                "reason": "MuJoCoはLinux GPIOではなくロボット物理を制御します。",
            },
        )

    def panel(self, action: str, params: dict[str, object]) -> HardwareControlResult:
        if action == "state":
            payload = _bridge_state(self.bridge_url)
            if payload is None:
                return HardwareControlResult(1, {"environment": "mujoco", "ok": False})
            return HardwareControlResult(0, payload)
        status, payload = _bridge_command(self.bridge_url, action, params)
        return HardwareControlResult(
            0 if status < 300 else 1,
            {
                "environment": "mujoco",
                "action": action,
                "ok": status < 300,
                "result": payload,
            },
        )


def _bridge_state(bridge_url: str) -> dict[str, object] | None:
    try:
        with urllib.request.urlopen(f"{bridge_url}/api/state", timeout=2) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _bridge_command(
    bridge_url: str,
    action: str,
    params: dict[str, object],
) -> tuple[int, dict[str, object] | str]:
    body = json.dumps({"action": action, "params": params}).encode("utf-8")
    request = urllib.request.Request(
        f"{bridge_url}/api/command",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")
    except urllib.error.URLError as exc:
        return 503, str(exc.reason)
    try:
        decoded = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return 200, raw
    return 200, decoded if isinstance(decoded, dict) else {"value": decoded}
