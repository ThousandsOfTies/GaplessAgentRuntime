"""Local MuJoCo simulation operations for GAR."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from scripts.gar_lib.config import PROJECT_ROOT
from scripts.gar_lib.environments.base import DevEnvironment
from scripts.gar_lib.simulation.base import SimCommandBuilder, SimEnvProcessor

DEFAULT_MODEL_PATH = PROJECT_ROOT / "examples" / "mujoco" / "pendulum.xml"
DEFAULT_WORKSPACE_DIR = PROJECT_ROOT / ".gar" / "mujoco"
DEFAULT_BRIDGE_URL = "http://127.0.0.1:8081"


class MujocoSimCommandBuilder(SimCommandBuilder):
    """Command descriptions for the local MuJoCo provider."""

    def build_gpio_systemd_install(self, hw_definition=None) -> str:
        return ":"

    def build_sim_diag_json(self, hw_definition=None) -> str:
        return "gar sim env diag --json"

    def build_gpio_sim_setup(self, hw_definition=None) -> str:
        return ":"

    def build_gpio_sim_teardown(self, hw_definition=None) -> str:
        return ":"

    def build_systemd_install(self, hw_definition=None) -> str:
        return ":"

    def build_systemd_start(self, hw_definition=None) -> str:
        return "python -m mujoco.viewer --mjcf=$GAR_MUJOCO_MODEL"

    def build_systemd_stop(self, hw_definition=None) -> str:
        return ":"

    def build_sim_start(self, hw_definition=None) -> str:
        return self.build_systemd_start(hw_definition)

    def build_sim_stop(self, hw_definition=None) -> str:
        return ":"

    def build_sim_status(self, hw_definition=None) -> str:
        return "gar sim env status --json"

    def build_sim_log(self) -> str:
        return "tail -f .gar/mujoco/mujoco.log"

    def build_gpio_runtime_status(self, hw_definition=None) -> str:
        return self.build_sim_status(hw_definition)

    def build_panel(self, action: str, params: dict) -> str:
        del action, params
        return ":"


class MujocoSimEnvProcessor(SimEnvProcessor):
    """Manage a MuJoCo JSON bridge and its optional standard viewer.

    ``GAR_MUJOCO_RUNNER`` may point at a Python executable owned by the product.
    GAR invokes it as ``runner --mjcf <model> --bridge-url <url>``.  The runner
    owns policies, hardware parameter fitting, trace export, and real-device
    adapters, but must expose the JSON bridge contract documented in
    ``docs/06_SIMULATION.md``.  Without it GAR launches its generic bridge.
    """

    def __init__(self, dev_env: type[DevEnvironment], host: str | None = None):
        self.dev_env = dev_env
        self.host = host
        self.builder = MujocoSimCommandBuilder()
        self.workspace_dir = Path(os.environ.get("GAR_MUJOCO_WORKSPACE", DEFAULT_WORKSPACE_DIR)).expanduser().resolve()
        self.state_path = self.workspace_dir / "state.json"
        self.log_path = self.workspace_dir / "mujoco.log"

    def _model_path(self) -> Path:
        return Path(os.environ.get("GAR_MUJOCO_MODEL", DEFAULT_MODEL_PATH)).expanduser().resolve()

    def _runner_path(self) -> Path | None:
        value = os.environ.get("GAR_MUJOCO_RUNNER")
        return Path(value).expanduser().resolve() if value else None

    def _bridge_url(self) -> str:
        return os.environ.get("GAR_MUJOCO_BRIDGE_URL", DEFAULT_BRIDGE_URL).rstrip("/")

    def _state(self) -> dict:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_state(self, state: dict) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _payload(self, *, status: str, ok: bool, **extra) -> dict:
        return {
            "provider": "mujoco",
            "status": status,
            "ok": ok,
            "model": str(self._model_path()),
            "runner": str(self._runner_path()) if self._runner_path() else None,
            "bridge_url": self._bridge_url(),
            **extra,
        }

    @staticmethod
    def _print(payload: dict, json_output: bool) -> None:
        if json_output:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        for key, value in payload.items():
            print(f"{key}: {value}")

    def _validate_model(self) -> tuple[bool, str | None]:
        model = self._model_path()
        if not model.is_file():
            return False, f"MJCF/URDF model not found: {model}"
        result = subprocess.run(
            [sys.executable, "-c", "import mujoco, sys; mujoco.MjModel.from_xml_path(sys.argv[1])", str(model)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            return False, (result.stderr or result.stdout).strip() or "MuJoCo could not load model"
        return True, None

    def build(self, *, json_output: bool = False) -> int:
        ok, error = self._validate_model()
        self._print(self._payload(status="ready" if ok else "invalid", ok=ok, error=error), json_output)
        return 0 if ok else 1

    def start(self, hw_definition: dict[str, list[dict[str, str]]]) -> int:
        del hw_definition
        ok, error = self._validate_model()
        if not ok:
            self._print(self._payload(status="invalid", ok=False, error=error), False)
            return 1
        runner = self._runner_path()
        if runner is not None and not runner.is_file():
            self._print(self._payload(status="invalid", ok=False, error=f"MuJoCo runner not found: {runner}"), False)
            return 1
        if runner:
            command = [
                sys.executable,
                str(runner),
                "--mjcf",
                str(self._model_path()),
                "--bridge-url",
                self._bridge_url(),
            ]
        else:
            bridge = urllib.parse.urlparse(self._bridge_url())
            if bridge.scheme != "http" or bridge.hostname is None:
                self._print(
                    self._payload(
                        status="invalid",
                        ok=False,
                        error="GAR_MUJOCO_BRIDGE_URL must be an http://host:port URL",
                    ),
                    False,
                )
                return 1
            command = [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "mujoco_bridge.py"),
                "--mjcf",
                str(self._model_path()),
                "--host",
                bridge.hostname,
                "--port",
                str(bridge.port or 80),
                "--viewer",
            ]
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as log:
            proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self._write_state({"pid": proc.pid, "command": command, "bridge_url": self._bridge_url()})
        self._print(self._payload(status="running", ok=True, pid=proc.pid), False)
        return 0

    def stop(self, hw_definition: dict[str, list[dict[str, str]]]) -> int:
        del hw_definition
        pid = self._state().get("pid")
        if isinstance(pid, int):
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        self._write_state({})
        self._print(self._payload(status="stopped", ok=True), False)
        return 0

    def status(self, hw_definition: dict[str, list[dict[str, str]]], json_output: bool = False) -> int:
        del hw_definition
        state = self._state()
        pid = state.get("pid")
        running = isinstance(pid, int) and _is_running(pid)
        bridge_state = self._bridge_state() if running else None
        ok = running and bridge_state is not None
        self._print(
            self._payload(
                status="running" if ok else ("degraded" if running else "stopped"),
                ok=ok,
                pid=pid if running else None,
                bridge_state=bridge_state,
            ),
            json_output,
        )
        return 0 if ok else 1

    def log(self) -> int:
        if not self.log_path.exists():
            print(f"MuJoCo log not found: {self.log_path}", file=sys.stderr)
            return 1
        print(self.log_path.read_text(encoding="utf-8"), end="")
        return 0

    def diag_json(self, hw_definition: dict[str, list[dict[str, str]]]) -> int:
        return self.status(hw_definition, json_output=True)

    def _bridge_state(self) -> dict | None:
        try:
            with urllib.request.urlopen(f"{self._bridge_url()}/api/state", timeout=2) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _bridge_command(self, action: str, params: dict) -> tuple[int, dict | str]:
        body = json.dumps({"action": action, "params": params}).encode("utf-8")
        request = urllib.request.Request(
            f"{self._bridge_url()}/api/command",
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
            return 200, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return 200, raw

    def gpio_sim_check(self, json_output: bool = False) -> int:
        self._print(self._payload(status="not-applicable", ok=True, reason="MuJoCo models robot physics rather than Linux GPIO"), json_output)
        return 0

    def gpio_command(self, command: str, hw_definition: dict[str, list[dict[str, str]]], json_output: bool = False) -> int:
        del command, hw_definition
        self._print(self._payload(status="unsupported", ok=True, reason="Use a product-owned MuJoCo runner for robot stimuli"), json_output)
        return 0

    def panel(self, action: str, params: dict, json_output: bool = False) -> int:
        if action == "state":
            payload = self._bridge_state()
            if payload is None:
                self._print(self._payload(status="unreachable", ok=False), json_output)
                return 1
            self._print(payload, json_output)
            return 0
        status, payload = self._bridge_command(action, params)
        result = {"provider": "mujoco", "action": action, "ok": status < 300, "result": payload}
        self._print(result, json_output)
        return 0 if status < 300 else 1


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
