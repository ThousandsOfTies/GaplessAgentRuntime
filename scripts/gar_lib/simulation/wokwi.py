"""Wokwi implementation of the SimulationEnvironment architecture."""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from scripts.gar_lib.access.local import ProcessChannel
from scripts.gar_lib.artifacts.manifest import load_deploy_files, resolve_artifact_src
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.simulation.diagnostic import PayloadSimulationDiagnostic

DEFAULT_TIMEOUT_MS = 30000


class WokwiSimulationEnvironment:
    requires_runtime_artifact = False
    runtime_host: str | None = None

    def __init__(self, project_dir: Path, process_channel: ProcessChannel):
        self.project_dir = project_dir
        self.process_channel = process_channel
        self.state_path = project_dir / "state.json"
        self.log_path = project_dir / "wokwi.log"

    def deploy(self, artifact: Artifact) -> None:
        if artifact.kind is not ArtifactKind.SIM_APP:
            raise GarDomainError("Wokwiには個別のsimulation runtime artifact配置は不要です。")
        loaded = load_deploy_files(artifact.bundle_path, "app")
        if loaded is None:
            raise GarDomainError(f"Wokwi artifact manifestを読み込めません: {artifact.bundle_path}")
        bundle_root, files = loaded
        self.project_dir.mkdir(parents=True, exist_ok=True)
        for entry in files:
            source = resolve_artifact_src(bundle_root, entry["src"])
            if source is None:
                raise GarDomainError(f"Wokwi artifact sourceがありません: {entry['src']}")
            destination = self._project_destination(entry["dest"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(source, destination)
            mode = entry.get("mode")
            if isinstance(mode, str):
                destination.chmod(int(mode, 8))

    def start(self, hardware: dict[str, list[dict[str, str]]]) -> int:
        del hardware
        self._require_project()
        state = self._state()
        pid = state.get("pid")
        if isinstance(pid, int) and self.process_channel.is_running(pid):
            self._print_status(running=True, pid=pid)
            return 0

        executable = self._wokwi_executable()
        if executable is None:
            raise GarDomainError("wokwi-cliが見つかりません。gar setupでWokwiを設定してください。")
        firmware = self._resolve_project_path(self._firmware_path())
        if not firmware.is_file():
            raise GarDomainError(f"Wokwi firmwareがありません。先にgar sim buildを実行してください: {firmware}")

        timeout = self._timeout_ms()
        argv = (
            executable,
            str(self.project_dir),
            "--serial-log-file",
            str(self.log_path),
            "--timeout",
            str(timeout),
            *(("--timeout-exit-code", "0") if timeout > 0 else ()),
        )
        launched = self.process_channel.start(argv, cwd=self.project_dir, log_path=self.log_path)
        self._write_state(
            {
                "environment": "wokwi",
                "pid": launched.pid,
                "argv": list(launched.argv),
                "project_dir": str(self.project_dir),
                "log": str(self.log_path),
                "started_at": datetime.now(UTC).isoformat(),
                "timeout_ms": timeout,
            }
        )
        self._print_status(running=True, pid=launched.pid)
        return 0

    def stop(self, hardware: dict[str, list[dict[str, str]]]) -> int:
        del hardware
        state = self._state()
        pid = state.get("pid")
        if isinstance(pid, int) and self.process_channel.is_running(pid):
            self.process_channel.terminate_group(pid)
        self._write_state(
            {
                **state,
                "status": "stopped",
                "stopped_at": datetime.now(UTC).isoformat(),
            }
        )
        self._print_status(running=False, pid=pid if isinstance(pid, int) else None)
        return 0

    def status(self, hardware: dict[str, list[dict[str, str]]]) -> int:
        del hardware
        state = self._state()
        pid = state.get("pid")
        running = isinstance(pid, int) and self.process_channel.is_running(pid)
        self._print_status(running=running, pid=pid if isinstance(pid, int) else None)
        return 0

    def diag(self, hardware: dict[str, list[dict[str, str]]]) -> PayloadSimulationDiagnostic:
        del hardware
        executable = self._wokwi_executable()
        firmware = self._resolve_project_path(self._firmware_path())
        elf = self._resolve_project_path(self._elf_path())
        files = {
            "project": self.project_dir.is_dir(),
            "diagram": (self.project_dir / "diagram.json").is_file(),
            "wokwi_toml": (self.project_dir / "wokwi.toml").is_file(),
            "firmware": firmware.is_file(),
            "elf": elf.is_file(),
        }
        return PayloadSimulationDiagnostic(
            {
                "environment": "wokwi",
                "project_dir": str(self.project_dir),
                "files": files,
                "cli": executable,
                "token": bool(os.environ.get("WOKWI_CLI_TOKEN")),
                "ok": all(files.values()) and executable is not None,
            }
        )

    def log(self) -> int:
        if not self.log_path.is_file():
            raise GarDomainError(f"Wokwi logがありません: {self.log_path}")
        print(self.log_path.read_text(encoding="utf-8", errors="replace"), end="")
        return 0

    def _require_project(self) -> None:
        if not self.project_dir.is_dir() or not (self.project_dir / "wokwi.toml").is_file():
            raise GarDomainError(
                f"Wokwi projectがありません。先にgar sim buildを実行してください: {self.project_dir}"
            )

    def _project_destination(self, value: str) -> Path:
        destination = Path(value)
        if destination.is_absolute() or value.startswith("~") or ".." in destination.parts:
            raise GarDomainError(f"Wokwi artifactのdestはproject相対pathで指定してください: {value}")
        return self.project_dir / destination

    def _wokwi_executable(self) -> str | None:
        home = Path.home()
        return self.process_channel.find_executable(
            "wokwi-cli",
            candidates=(home / "bin" / "wokwi-cli", home / ".wokwi" / "bin" / "wokwi-cli"),
        )

    def _firmware_path(self) -> str:
        return os.environ.get("GAR_WOKWI_FIRMWARE", ".pio/build/m5stackc/firmware.bin")

    def _elf_path(self) -> str:
        return os.environ.get("GAR_WOKWI_ELF", ".pio/build/m5stackc/firmware.elf")

    def _resolve_project_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else self.project_dir / path

    def _timeout_ms(self) -> int:
        raw = os.environ.get("GAR_WOKWI_TIMEOUT_MS")
        try:
            return max(0, int(raw)) if raw is not None else DEFAULT_TIMEOUT_MS
        except ValueError:
            return DEFAULT_TIMEOUT_MS

    def _state(self) -> dict[str, object]:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_state(self, payload: dict[str, object]) -> None:
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _print_status(self, *, running: bool, pid: int | None) -> None:
        print("environment: wokwi")
        print(f"status: {'running' if running else 'stopped'}")
        print(f"pid: {pid if pid is not None else '(none)'}")
        print(f"project: {self.project_dir}")
