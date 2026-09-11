"""Wokwi implementation of the SimulationEnvironment architecture."""

from __future__ import annotations

import os
import shutil
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from scripts.gar_lib.artifacts.manifest import load_deploy_files, resolve_artifact_src
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.observation import component, unavailable
from scripts.gar_lib.simulation.diagnostics.model import PayloadSimulationDiagnostic
from scripts.gar_lib.simulation.runtime.deployment import deployment_record
from scripts.gar_lib.simulation.runtime.local_identity import LocalApplicationIdentity
from scripts.gar_lib.simulation.runtime.process import (
    ManagedProcess,
    ProcessChannel,
    ProcessStateStore,
)

DEFAULT_TIMEOUT_MS = 30000


class WokwiSimulationEnvironment:
    requires_runtime_artifact = False
    session_host: str | None = None

    def __init__(self, project_dir: Path, process_channel: ProcessChannel):
        project_dir = Path(os.path.abspath(project_dir.expanduser()))
        self.project_dir = project_dir
        self.process_channel = process_channel
        self.state_path = project_dir / "state.json"
        self.state_store = ProcessStateStore(self.state_path)
        self.log_path = project_dir / "wokwi.log"
        self.identity = LocalApplicationIdentity(project_dir)

    def deploy(self, artifact: Artifact) -> None:
        self._prepare_project_root()
        with self.state_store.locked():
            self._deploy(artifact)

    def _deploy(self, artifact: Artifact) -> None:
        if artifact.kind is not ArtifactKind.SIM_APP:
            raise GarDomainError("Wokwiには個別のsimulation runtime artifact配置は不要です。")
        loaded = load_deploy_files(artifact.bundle_path, "app")
        if loaded is None:
            raise GarDomainError(f"Wokwi artifact manifestを読み込めません: {artifact.bundle_path}")
        bundle_root, files = loaded
        receipt = deployment_record(bundle_root, files, self._project_destination)
        self.identity.begin(receipt)
        for entry in files:
            self._reject_source_symlinks(bundle_root, entry["src"])
            source = resolve_artifact_src(bundle_root, entry["src"])
            if source is None:
                raise GarDomainError(f"Wokwi artifact sourceがありません: {entry['src']}")
            destination = self._project_destination(entry["dest"])
            if source.is_dir():
                self._copy_directory(source, destination, entry["dest"])
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists() and destination.is_dir():
                    raise GarDomainError(f"Wokwi artifact fileの配置先がdirectoryです: {destination}")
                shutil.copy2(source, destination)
            mode = entry.get("mode")
            if isinstance(mode, str):
                destination.chmod(int(mode, 8))
        self.identity.finish(receipt)

    def start(self, hardware: dict[str, list[dict[str, str]]]) -> int:
        del hardware
        self._require_project()
        with self.state_store.locked():
            state = self._state()
            current_process = ManagedProcess.from_state(state)
            if current_process is not None and self.process_channel.owns(current_process):
                self._print_status(running=True, pid=current_process.pid)
                return 0

            executable = self._wokwi_executable()
            if executable is None:
                raise GarDomainError("wokwi-cliが見つかりません。gar configでWokwiを設定してください。")
            firmware = self._resolve_project_path(self._firmware_path())
            if not firmware.is_file():
                raise GarDomainError(
                    f"Wokwi firmwareがありません。先にgar sim build appとgar sim deploy appを実行してください: {firmware}"
                )

            timeout = self._timeout_ms()
            required = self._identity_inputs()
            before = self.identity.capture(required) if required else {}
            launch_dir = self.identity.stage(before, self.project_dir)
            if launch_dir is None:
                before = {}
            argv = (
                executable,
                str(launch_dir or self.project_dir),
                "--serial-log-file",
                str(self.log_path),
                "--timeout",
                str(timeout),
                *(("--timeout-exit-code", "0") if timeout > 0 else ()),
            )
            launched = self.process_channel.start(argv, cwd=launch_dir or self.project_dir, log_path=self.log_path)
            try:
                self._write_state(
                    {
                        "environment": "wokwi",
                        **launched.to_state(),
                        "project_dir": str(self.project_dir),
                        "log": str(self.log_path),
                        "started_at": datetime.now(UTC).isoformat(),
                        "timeout_ms": timeout,
                        "app_build": self.identity.launched(before, required),
                    }
                )
            except Exception:
                self.process_channel.terminate_group(launched)
                raise
        self._print_status(running=True, pid=launched.pid)
        return 0

    def stop(self, hardware: dict[str, list[dict[str, str]]]) -> int:
        del hardware
        with self.state_store.locked():
            state = self._state()
            process = ManagedProcess.from_state(state)
            if process is not None:
                self.process_channel.terminate_group(process)
            self._write_state(
                {
                    **state,
                    "status": "stopped",
                    "stopped_at": datetime.now(UTC).isoformat(),
                }
            )
        self._print_status(running=False, pid=process.pid if process is not None else None)
        return 0

    def status(self, hardware: dict[str, list[dict[str, str]]]) -> int:
        del hardware
        state = self._state()
        process = ManagedProcess.from_state(state)
        running = process is not None and self.process_channel.owns(process)
        self._print_status(running=running, pid=process.pid if process is not None else None)
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

    def _identity_inputs(self) -> tuple[Path, ...]:
        try:
            configuration = tomllib.loads((self.project_dir / "wokwi.toml").read_text(encoding="utf-8"))
            firmware = configuration["wokwi"]["firmware"]
            if not isinstance(firmware, str) or not firmware:
                return ()
            if Path(firmware).is_absolute() or ".." in Path(firmware).parts:
                return ()
            return (
                self.project_dir / "wokwi.toml",
                self.project_dir / "diagram.json",
                self._resolve_project_path(firmware),
            )
        except (OSError, ValueError, KeyError, TypeError):
            return ()

    def _require_project(self) -> None:
        if not self.project_dir.is_dir() or not (self.project_dir / "wokwi.toml").is_file():
            raise GarDomainError(
                f"Wokwi projectがありません。先にgar sim build appとgar sim deploy appを実行してください: {self.project_dir}"
            )

    def _prepare_project_root(self) -> None:
        absolute_project_dir = Path(os.path.abspath(self.project_dir))
        current = Path(absolute_project_dir.anchor)
        for part in absolute_project_dir.parts[1:]:
            current /= part
            if current.is_symlink():
                raise GarDomainError(f"Wokwi project pathはsymlinkにできません: {current}")
        self.project_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _reject_source_symlinks(bundle_root: Path, source_text: str) -> None:
        source_path = Path(source_text)
        if source_path.is_absolute() or ".." in source_path.parts:
            return

        current = bundle_root
        for part in source_path.parts:
            current /= part
            if current.is_symlink():
                raise GarDomainError(f"Wokwi artifact sourceはsymlinkにできません: {current}")

    def _copy_directory(self, source: Path, destination: Path, destination_text: str) -> None:
        source_entries = sorted(source.rglob("*"))
        symlink = next((entry for entry in source_entries if entry.is_symlink()), None)
        if symlink is not None:
            raise GarDomainError(f"Wokwi artifact sourceはsymlinkを含められません: {symlink}")
        if destination.exists() and not destination.is_dir():
            raise GarDomainError(f"Wokwi artifact directoryの配置先がfileです: {destination}")

        destination.mkdir(parents=True, exist_ok=True)
        destination_base = Path(destination_text)
        for source_entry in source_entries:
            relative = source_entry.relative_to(source)
            target = self._project_destination((destination_base / relative).as_posix())
            if source_entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif source_entry.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_entry, target)

    def _project_destination(self, value: str) -> Path:
        destination = Path(value)
        if destination.is_absolute() or value.startswith("~") or ".." in destination.parts:
            raise GarDomainError(f"Wokwi artifactのdestはproject相対pathで指定してください: {value}")
        current = self.project_dir
        for index, part in enumerate(destination.parts):
            current /= part
            if current.is_symlink():
                raise GarDomainError(f"Wokwi artifactのdestはsymlinkを通れません: {current}")
            if index < len(destination.parts) - 1 and current.exists() and not current.is_dir():
                raise GarDomainError(f"Wokwi artifactのdest親pathがdirectoryではありません: {current}")
        return current

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
        return self.state_store.read()

    def _write_state(self, payload: dict[str, object]) -> None:
        self.state_store.write(payload)

    def _print_status(self, *, running: bool, pid: int | None) -> None:
        print("environment: wokwi")
        print(f"status: {'running' if running else 'stopped'}")
        print(f"pid: {pid if pid is not None else '(none)'}")
        print(f"project: {self.project_dir}")
