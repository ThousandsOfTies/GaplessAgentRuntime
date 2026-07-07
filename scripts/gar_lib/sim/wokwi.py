"""Wokwi simulation target implementation for ESP32/M5Stack-class boards."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from scripts.gar_lib.config import PROJECT_ROOT
from scripts.gar_lib.gar_tools import gar_tools_root
from scripts.gar_lib.environments.base import DevEnvironment
from scripts.gar_lib.sim.base import SimCommandBuilder, SimEnvProcessor

DEFAULT_WOKWI_WORKSPACE_DIR = PROJECT_ROOT / ".gar" / "wokwi" / "m5stackc"
DEFAULT_WOKWI_DIR = DEFAULT_WOKWI_WORKSPACE_DIR
DEFAULT_WOKWI_TEMPLATE_REL = Path("targets") / "esp32" / "wokwi" / "m5stackc"
IGNORED_TEMPLATE_PARTS = {".git", ".pio", "__pycache__"}
DEFAULT_TIMEOUT_MS = 30000
VIBE_REMOTE_M5_SRC_REL = Path("vibe-remote") / "m5stickc-client" / "src"


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


def _template_dir() -> Path:
    raw = os.environ.get("GAR_WOKWI_TEMPLATE_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return gar_tools_root() / DEFAULT_WOKWI_TEMPLATE_REL


def _vibe_remote_m5_src_dir() -> Path | None:
    raw = os.environ.get("GAR_VIBE_REMOTE_M5_SRC_DIR")
    if raw:
        path = Path(raw).expanduser().resolve()
        return path if path.is_dir() else None

    for candidate in (
        PROJECT_ROOT.parent / "gar-vibe-ui" / VIBE_REMOTE_M5_SRC_REL,
        PROJECT_ROOT / "gar-vibe-ui" / VIBE_REMOTE_M5_SRC_REL,
    ):
        if candidate.is_dir():
            return candidate
    return None


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


class WokwiSimEnvProcessor(SimEnvProcessor):
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

    def _workspace_context(self) -> dict[str, str | None]:
        app_src_dir = _vibe_remote_m5_src_dir()
        return {
            "workspace_dir": str(self.project_dir),
            "project_dir": str(self.project_dir),
            "template_dir": str(_template_dir()),
            "app_src_dir": str(app_src_dir) if app_src_dir else None,
        }

    def _relative_path_exists(self, path_text: str) -> bool:
        path = Path(path_text)
        if not path.is_absolute():
            path = self.project_dir / path
        return path.exists()

    def _copy_template_file(self, source: Path, relative_path: Path) -> None:
        dest = self.project_dir / relative_path
        if source.resolve() == dest.resolve():
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
            relative_path = source.relative_to(template_dir)
            if any(part in IGNORED_TEMPLATE_PARTS for part in relative_path.parts):
                continue
            if not source.is_file() or source.name in {"platformio.ini.template", "wokwi.toml.template"}:
                continue
            self._copy_template_file(source, relative_path)

        self._remove_legacy_app_source_dir()
        platformio_ini = self._render_platformio_ini(template_dir)
        if platformio_ini is not None:
            (self.project_dir / "platformio.ini").write_text(platformio_ini, encoding="utf-8")
        (self.project_dir / "wokwi.toml").write_text(self._render_wokwi_toml(template_dir), encoding="utf-8")

    def _remove_legacy_app_source_dir(self) -> None:
        dest = self.project_dir / "src"
        if dest.is_symlink():
            dest.unlink()
            return
        if dest.is_dir():
            shutil.rmtree(dest)

    def _render_platformio_ini(self, template_dir: Path) -> str | None:
        template_path = template_dir / "platformio.ini.template"
        if not template_path.exists():
            return None

        app_src_dir = _vibe_remote_m5_src_dir()
        if app_src_dir is None:
            raise FileNotFoundError(
                "Vibe Remote M5 app source not found. "
                "Clone gar-vibe-ui next to GaplessAgentRuntime or set GAR_VIBE_REMOTE_M5_SRC_DIR."
            )

        template = template_path.read_text(encoding="utf-8")
        app_src = os.path.relpath(app_src_dir, self.project_dir)
        return template.format(app_src=Path(app_src).as_posix())

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
        except (FileExistsError, FileNotFoundError) as exc:
            self._print_payload(
                {
                    "provider": "wokwi",
                    "status": "template-missing",
                    **self._workspace_context(),
                    "ok": False,
                    "error": str(exc),
                    "hint": "Run `gar setup` to fetch gar-tools into .gar/tools, or set GAR_WOKWI_TEMPLATE_DIR.",
                },
                json_output=json_output,
            )
            return 1
        self._print_payload(
            {
                "provider": "wokwi",
                "status": "project-ready",
                **self._workspace_context(),
                "diagram": str(self.project_dir / "diagram.json"),
                "wokwi_toml": str(self.project_dir / "wokwi.toml"),
                "ok": True,
            },
            json_output=json_output,
        )
        return 0

    def build(self, *, json_output: bool = False) -> int:
        client_dir = PROJECT_ROOT.parent / "gar-vibe-ui" / "vibe-remote" / "m5stickc-client"
        if not (client_dir / "Makefile").is_file():
            print(f"gar sim env build: Wokwi client Makefile が見つかりません: {client_dir}")
            return 1

        env = os.environ.copy()
        platformio_bin = Path.home() / ".venvs" / "platformio" / "bin"
        env["PATH"] = f"{platformio_bin}:{Path.home() / 'bin'}:{env.get('PATH', '')}"

        if not json_output:
            print("gar sim env build: Wokwi firmware build を実行します。")
            print(f"  cwd: {client_dir}")
            print("  command: make wokwi-build")

        result = subprocess.run(
            ["make", "wokwi-build"],
            cwd=client_dir,
            env=env,
            stdout=sys.stderr if json_output else None,
            stderr=sys.stderr if json_output else None,
        )
        if json_output:
            print(
                json.dumps(
                    {
                        "command": "sim env build",
                        "provider": "wokwi",
                        "cwd": str(client_dir),
                        "delegated_command": "make wokwi-build",
                        "ok": result.returncode == 0,
                        "exit_code": result.returncode,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return result.returncode

    def _start_cli(self) -> int:
        cli = shutil.which("wokwi-cli")
        firmware = self._firmware_path()
        if not cli:
            self._print_payload(
                {
                    "provider": "wokwi",
                    **self._workspace_context(),
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
                    **self._workspace_context(),
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
                **self._workspace_context(),
                "log": str(self.log_path),
                "started_at": _now_iso(),
                "timeout_ms": timeout,
            }
        )
        self._print_payload({"provider": "wokwi", "status": "running", "pid": proc.pid, **self._workspace_context(), "ok": True})
        return 0

    def start(self, hw_definition: dict[str, list[dict[str, str]]]) -> int:
        try:
            self._ensure_project(hw_definition)
        except FileNotFoundError as exc:
            self._print_payload(
                {
                    "provider": "wokwi",
                    "status": "template-missing",
                    **self._workspace_context(),
                    "ok": False,
                    "error": str(exc),
                    "hint": "Run `gar setup` to fetch gar-tools into .gar/tools, or set GAR_WOKWI_TEMPLATE_DIR.",
                }
            )
            return 1
        state = self._state()
        pid = state.get("pid")
        if isinstance(pid, int) and _is_pid_running(pid):
            self._print_payload({"provider": "wokwi", "status": "running", "pid": pid, **self._workspace_context(), "ok": True})
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
            **self._workspace_context(),
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
            **self._workspace_context(),
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
        if action in {"button-press", "button-set"}:
            return self._run_button_action(action, params, json_output=json_output)
        self._print_payload(
            {"provider": "wokwi", "action": action, "params": params, "ok": True, "status": "unsupported", "reason": "Wokwi UI/scenarios replace the Linux virtual hardware panel"},
            json_output=json_output,
        )
        return 0

    def _run_button_action(self, action: str, params: dict, *, json_output: bool = False) -> int:
        cli = shutil.which("wokwi-cli")
        if not cli:
            self._print_payload(
                {
                    "provider": "wokwi",
                    "action": action,
                    "params": params,
                    "ok": False,
                    "status": "missing-cli",
                    "hint": "Install wokwi-cli or run `gar setup`.",
                },
                json_output=json_output,
            )
            return 1

        try:
            self._ensure_project({})
            part_id = _wokwi_button_part(params)
        except (FileNotFoundError, ValueError) as exc:
            self._print_payload(
                {
                    "provider": "wokwi",
                    "action": action,
                    "params": params,
                    "ok": False,
                    "status": "invalid-button",
                    "error": str(exc),
                },
                json_output=json_output,
            )
            return 1

        if not self._relative_path_exists(self._firmware_path()):
            self._print_payload(
                {
                    "provider": "wokwi",
                    "action": action,
                    "params": params,
                    "ok": False,
                    "status": "missing-firmware",
                    "firmware": self._firmware_path(),
                    "hint": "Run `pio run` in the Wokwi project or set GAR_WOKWI_FIRMWARE.",
                },
                json_output=json_output,
            )
            return 1

        scenario = self._button_scenario(action, part_id, params)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".test.yaml", delete=False) as f:
            f.write(scenario)
            scenario_path = Path(f.name)
        try:
            argv = [
                cli,
                "--scenario",
                str(scenario_path),
                "--serial-log-file",
                str(self.log_path),
                "--timeout",
                str(self._timeout_ms()),
                str(self.project_dir),
            ]
            result = subprocess.run(argv, cwd=self.project_dir, check=False)
        finally:
            scenario_path.unlink(missing_ok=True)

        self._print_payload(
            {
                "provider": "wokwi",
                "action": action,
                "button": part_id,
                "project_dir": str(self.project_dir),
                "log": str(self.log_path),
                "ok": result.returncode == 0,
                "exit_code": result.returncode,
            },
            json_output=json_output,
        )
        return result.returncode

    def _button_scenario(self, action: str, part_id: str, params: dict) -> str:
        value = 1 if int(params.get("value", 1)) else 0
        if action == "button-set":
            return _wokwi_scenario(
                [
                    _set_control_step(part_id, value),
                ]
            )
        duration_ms = max(0, int(params.get("duration_ms", 150)))
        return _wokwi_scenario(
            [
                _set_control_step(part_id, 1),
                f"  - delay: {duration_ms}ms",
                _set_control_step(part_id, 0),
            ]
        )


def _wokwi_button_part(params: dict) -> str:
    value = str(params.get("button") or params.get("line") or "A").strip()
    aliases = {
        "a": "btnA",
        "btna": "btnA",
        "32": "btnA",
        "37": "btnA",
        "b": "btnB",
        "btnb": "btnB",
        "33": "btnB",
        "39": "btnB",
    }
    key = value.lower()
    if key in aliases:
        return aliases[key]
    raise ValueError(f"unknown Wokwi button: {value}")


def _wokwi_scenario(steps: list[str]) -> str:
    return (
        'name: "GAR generated Wokwi input"\n'
        "version: 1\n"
        "author: \"Gapless Agent Runtime\"\n"
        "\n"
        "steps:\n"
        + "\n".join(steps)
        + "\n"
    )


def _set_control_step(part_id: str, value: int) -> str:
    return (
        "  - set-control:\n"
        f"      part-id: {part_id}\n"
        "      control: pressed\n"
        f"      value: {value}"
    )
