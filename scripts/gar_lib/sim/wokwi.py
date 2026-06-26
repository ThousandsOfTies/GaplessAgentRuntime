"""Wokwi simulation target implementation for ESP32/M5Stack-class boards."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from scripts.gar_lib._config import PROJECT_ROOT
from scripts.gar_lib.environments.base import DevEnvironment
from scripts.gar_lib.sim.base import SimCommandBuilder, SimProvider

DEFAULT_WOKWI_DIR = PROJECT_ROOT / ".gar" / "wokwi" / "m5stackc"
DEFAULT_WOKWI_TEMPLATE_REL = Path("targets") / "esp32" / "wokwi" / "m5stackc"
DEFAULT_TIMEOUT_MS = 30000


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    if not raw:
        return default
    return Path(raw).expanduser().resolve()


def _is_pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _gar_tools_root() -> Path:
    raw = os.environ.get("GAR_TOOLS_ROOT")
    if raw:
        return Path(raw).expanduser().resolve()
    return (PROJECT_ROOT.parent / "gar-tools").resolve()


def _template_dir() -> Path:
    raw = os.environ.get("GAR_WOKWI_TEMPLATE_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return _gar_tools_root() / DEFAULT_WOKWI_TEMPLATE_REL


class WokwiSimCommandBuilder(SimCommandBuilder):
    """Generates local shell commands for Wokwi simulation operations."""

    def build_gpio_systemd_install(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return ":"

    def build_sim_diag_json(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return "gar sim env diag --json"

    def build_gpio_sim_setup(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return ":"

    def build_gpio_sim_teardown(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return ":"

    def build_systemd_install(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return ":"

    def build_systemd_start(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return "wokwi-cli ."

    def build_systemd_stop(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return ":"

    def build_sim_start(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return "wokwi-cli ."

    def build_sim_stop(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return ":"

    def build_sim_status(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return "gar sim env status --json"

    def build_sim_log(self) -> str:
        return "tail -f .gar/wokwi/m5stackc/wokwi.log"

    def build_gpio_runtime_status(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        return "gar sim env status --json"

    def build_panel(self, action: str, params: dict) -> str:
        return ":"


class WokwiSimProvider(SimProvider):
    """High-level Wokwi simulation operations.

    The provider creates a local Wokwi project for an M5StickC/M5StackC-style
    ESP32 setup. If `wokwi-cli` and firmware are available it starts the CLI in
    the background; otherwise it still leaves a ready-to-fill project on disk.
    """

    def __init__(self, dev_env: type[DevEnvironment], host: str | None = None):
        self.dev_env = dev_env
        self.host = host
        self.builder = WokwiSimCommandBuilder()
        self.project_dir = _env_path("GAR_WOKWI_PROJECT_DIR", DEFAULT_WOKWI_DIR)
        self.state_path = self.project_dir / "state.json"
        self.log_path = self.project_dir / "wokwi.log"

    def _print_payload(self, payload: dict, *, json_output: bool = False) -> None:
        if json_output:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        for key, value in payload.items():
            if isinstance(value, dict | list):
                value = json.dumps(value, ensure_ascii=False)
            print(f"{key}: {value}")

    def _firmware_path(self) -> str:
        return os.environ.get("GAR_WOKWI_FIRMWARE", ".pio/build/m5stackc/firmware.bin")

    def _elf_path(self) -> str:
        return os.environ.get("GAR_WOKWI_ELF", ".pio/build/m5stackc/firmware.elf")

    def _timeout_ms(self) -> int:
        raw = os.environ.get("GAR_WOKWI_TIMEOUT_MS")
        if raw is None:
            return DEFAULT_TIMEOUT_MS
        try:
            return max(0, int(raw))
        except ValueError:
            return DEFAULT_TIMEOUT_MS

    def _state(self) -> dict:
        if not self.state_path.exists():
            return {}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_state(self, payload: dict) -> None:
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _relative_path_exists(self, path_text: str) -> bool:
        path = Path(path_text)
        if not path.is_absolute():
            path = self.project_dir / path
        return path.exists()

    def _write_if_missing(self, name: str, content: str) -> None:
        path = self.project_dir / name
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _copy_template_file_if_missing(self, source: Path, relative_path: Path) -> None:
        dest = self.project_dir / relative_path
        if dest.exists():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)

    def _ensure_project(self, hw_definition: dict[str, list[dict[str, str]]]) -> None:
        del hw_definition
        self.project_dir.mkdir(parents=True, exist_ok=True)
        template_dir = _template_dir()
        if not template_dir.is_dir():
            raise FileNotFoundError(f"Wokwi template directory not found: {template_dir}")

        for source in sorted(template_dir.rglob("*")):
            if not source.is_file() or source.name == "wokwi.toml.template":
                continue
            self._copy_template_file_if_missing(source, source.relative_to(template_dir))

        self._write_if_missing("wokwi.toml", self._render_wokwi_toml(template_dir))

    def _render_wokwi_toml(self, template_dir: Path) -> str:
        template_path = template_dir / "wokwi.toml.template"
        if template_path.exists():
            template = template_path.read_text(encoding="utf-8")
            return template.format(firmware=self._firmware_path(), elf=self._elf_path())
        return (
            "[wokwi]\n"
            "version = 1\n"
            f"firmware = '{self._firmware_path()}'\n"
            f"elf = '{self._elf_path()}'\n"
            "rfc2217ServerPort = 4000\n"
        )

    def prepare_project(self, hw_definition: dict[str, list[dict[str, str]]], *, json_output: bool = False) -> int:
        try:
            self._ensure_project(hw_definition)
        except FileNotFoundError as exc:
            self._print_payload(
                {
                    "provider": "wokwi",
                    "status": "template-missing",
                    "project_dir": str(self.project_dir),
                    "ok": False,
                    "error": str(exc),
                    "hint": "Install or clone gar-tools next to GaplessAgentRuntime, or set GAR_WOKWI_TEMPLATE_DIR.",
                },
                json_output=json_output,
            )
            return 1
        self._print_payload(
            {
                "provider": "wokwi",
                "status": "project-ready",
                "project_dir": str(self.project_dir),
                "diagram": str(self.project_dir / "diagram.json"),
                "wokwi_toml": str(self.project_dir / "wokwi.toml"),
                "ok": True,
            },
            json_output=json_output,
        )
        return 0

    def _start_cli(self) -> int:
        cli = shutil.which("wokwi-cli")
        firmware = self._firmware_path()
        if not cli:
            self._print_payload(
                {
                    "provider": "wokwi",
                    "project_dir": str(self.project_dir),
                    "status": "project-ready",
                    "ok": True,
                    "warning": "wokwi-cli not found; install it to run the simulation",
                }
            )
            return 0
        if not self._relative_path_exists(firmware):
            self._print_payload(
                {
                    "provider": "wokwi",
                    "project_dir": str(self.project_dir),
                    "status": "project-ready",
                    "ok": True,
                    "warning": f"firmware not found: {firmware}; run `pio run` or set GAR_WOKWI_FIRMWARE",
                }
            )
            return 0

        timeout = self._timeout_ms()
        argv = [cli, str(self.project_dir), "--serial-log-file", str(self.log_path), "--timeout", str(timeout)]
        if timeout > 0:
            argv.extend(["--timeout-exit-code", "0"])
        log = self.log_path.open("ab")
        try:
            proc = subprocess.Popen(argv, cwd=self.project_dir, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        finally:
            log.close()
        self._write_state(
            {
                "provider": "wokwi",
                "pid": proc.pid,
                "argv": argv,
                "project_dir": str(self.project_dir),
                "log": str(self.log_path),
                "started_at": _now_iso(),
                "timeout_ms": timeout,
            }
        )
        self._print_payload({"provider": "wokwi", "status": "running", "pid": proc.pid, "project_dir": str(self.project_dir), "ok": True})
        return 0

    def start(self, hw_definition: dict[str, list[dict[str, str]]]) -> int:
        try:
            self._ensure_project(hw_definition)
        except FileNotFoundError as exc:
            self._print_payload(
                {
                    "provider": "wokwi",
                    "status": "template-missing",
                    "project_dir": str(self.project_dir),
                    "ok": False,
                    "error": str(exc),
                    "hint": "Install or clone gar-tools next to GaplessAgentRuntime, or set GAR_WOKWI_TEMPLATE_DIR.",
                }
            )
            return 1
        state = self._state()
        pid = state.get("pid")
        if isinstance(pid, int) and _is_pid_running(pid):
            self._print_payload({"provider": "wokwi", "status": "running", "pid": pid, "project_dir": str(self.project_dir), "ok": True})
            return 0
        return self._start_cli()

    def stop(self, hw_definition: dict[str, list[dict[str, str]]]) -> int:
        del hw_definition
        state = self._state()
        pid = state.get("pid")
        if not isinstance(pid, int) or not _is_pid_running(pid):
            self._write_state({**state, "stopped_at": _now_iso(), "status": "stopped"})
            self._print_payload({"provider": "wokwi", "status": "stopped", "ok": True})
            return 0
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        self._write_state({**state, "stopped_at": _now_iso(), "status": "stopped"})
        self._print_payload({"provider": "wokwi", "status": "stopped", "pid": pid, "ok": True})
        return 0

    def status(self, hw_definition: dict[str, list[dict[str, str]]], json_output: bool = False) -> int:
        del hw_definition
        state = self._state()
        pid = state.get("pid")
        running = isinstance(pid, int) and _is_pid_running(pid)
        payload = {
            "provider": "wokwi",
            "status": "running" if running else "stopped",
            "running": running,
            "pid": pid if isinstance(pid, int) else None,
            "project_dir": str(self.project_dir),
            "diagram": str(self.project_dir / "diagram.json"),
            "wokwi_toml": str(self.project_dir / "wokwi.toml"),
            "log": str(self.log_path),
            "cli": shutil.which("wokwi-cli"),
            "token": bool(os.environ.get("WOKWI_CLI_TOKEN")),
            "ok": True,
        }
        self._print_payload(payload, json_output=json_output)
        return 0

    def log(self) -> int:
        if not self.log_path.exists():
            print(f"wokwi log not found: {self.log_path}", file=sys.stderr)
            return 1
        print(self.log_path.read_text(encoding="utf-8", errors="replace"), end="")
        return 0

    def diag_json(self, hw_definition: dict[str, list[dict[str, str]]]) -> int:
        self._ensure_project(hw_definition)
        payload = {
            "provider": "wokwi",
            "ok": True,
            "project_dir": str(self.project_dir),
            "files": {
                "diagram": (self.project_dir / "diagram.json").exists(),
                "wokwi_toml": (self.project_dir / "wokwi.toml").exists(),
                "platformio": (self.project_dir / "platformio.ini").exists(),
                "firmware": self._relative_path_exists(self._firmware_path()),
                "elf": self._relative_path_exists(self._elf_path()),
            },
            "cli": shutil.which("wokwi-cli"),
            "token": bool(os.environ.get("WOKWI_CLI_TOKEN")),
            "m5stackc": {
                "board": "M5StickC/M5StackC-style ESP32",
                "display": "ILI9341-compatible TFT on SPI",
                "buttons": ["BtnA GPIO37", "BtnB GPIO39"],
            },
        }
        self._print_payload(payload, json_output=True)
        return 0

    def gpio_sim_check(self, json_output: bool = False) -> int:
        self._print_payload(
            {"provider": "wokwi", "gpio_sim": "not-applicable", "reason": "Wokwi models MCU pins directly", "ok": True},
            json_output=json_output,
        )
        return 0

    def gpio_command(self, command: str, hw_definition: dict[str, list[dict[str, str]]], json_output: bool = False) -> int:
        del hw_definition
        self._print_payload(
            {"provider": "wokwi", "command": command, "ok": True, "status": "unsupported", "reason": "Use Wokwi scenarios or serial input for MCU pin stimuli"},
            json_output=json_output,
        )
        return 0

    def panel(self, action: str, params: dict, json_output: bool = False) -> int:
        self._print_payload(
            {"provider": "wokwi", "action": action, "params": params, "ok": True, "status": "unsupported", "reason": "Wokwi UI/scenarios replace the Linux virtual hardware panel"},
            json_output=json_output,
        )
        return 0
