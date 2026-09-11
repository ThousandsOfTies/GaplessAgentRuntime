"""Linux/systemd simulation runtime composed with capability channels."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

from scripts.gar_lib.access.channel import CommandChannel, FileChannel
from scripts.gar_lib.artifacts.manifest import load_deploy_files, resolve_artifact_src
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.observation import component
from scripts.gar_lib.simulation.diagnostics.model import SimulationDiagnostic
from scripts.gar_lib.simulation.runtime.deployment import deployment_record, remote_deployment_command
from scripts.gar_lib.simulation.runtime.linux_commands import LinuxSystemdCommandBuilder


class LinuxSystemdSimulationEnvironment:
    requires_runtime_artifact = True

    _SECTIONS = {
        ArtifactKind.SIM_APP: "app",
        ArtifactKind.SIM_RUNTIME: "sim_env",
    }
    _DESTINATIONS = {
        "~/cuse_i2c": "/usr/local/sbin/cuse_i2c",
        "~/cuse_spi": "/usr/local/sbin/cuse_spi",
        "~/web-bridge": "/usr/local/lib/gar/web-bridge",
    }
    _SAFE_APPLICATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
    _SAFE_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

    def __init__(
        self,
        command_channel: CommandChannel,
        file_channel: FileChannel,
        command_builder: LinuxSystemdCommandBuilder,
        session_host: str | None = None,
    ):
        self.command_channel = command_channel
        self.file_channel = file_channel
        self.command_builder = command_builder
        self.session_host = session_host

    def deploy(self, artifact: Artifact) -> None:
        section = self._SECTIONS.get(artifact.kind)
        if section is None:
            raise GarDomainError(f"Linux simulationへ配置できないartifactです: {artifact.kind.value}")
        loaded = load_deploy_files(artifact.bundle_path, section)
        if loaded is None:
            raise GarDomainError(f"artifact manifestを読み込めません: {artifact.bundle_path}")
        bundle_root, files = loaded
        receipt = None
        if artifact.kind is ArtifactKind.SIM_APP:
            receipt = deployment_record(bundle_root, files, self._destination)
            self._write_deployment({**receipt, "state": "deploying"})

        if artifact.kind is ArtifactKind.SIM_RUNTIME:
            # Linux refuses to replace an executing CUSE binary (ETXTBSY).
            # Runtime deployment is intentionally followed by `gar sim runtime
            # start`, so stop every managed service before replacing files.
            stopped = self.command_channel.run(
                "sudo systemctl stop gar-sim.target gar-bridge.service "
                "'gar-cuse-i2c@*.service' 'gar-cuse-spi@*.service' || true"
            )
            if stopped.returncode != 0:
                raise GarDomainError("runtime停止に失敗しました")

        for entry in files:
            source = resolve_artifact_src(bundle_root, entry["src"])
            if source is None:
                raise GarDomainError(f"artifact sourceがありません: {entry['src']}")
            staging = f"/tmp/gar-deploy-{os.getpid()}-{source.name}"
            transferred = self.file_channel.push(source, staging)
            if transferred.returncode != 0:
                raise GarDomainError(f"artifact転送に失敗しました (exit {transferred.returncode})")

            destination = self._destination(entry["dest"])
            command = self._install_command(
                staging,
                destination,
                source_is_dir=source.is_dir(),
                mode=entry.get("mode") if isinstance(entry.get("mode"), str) else None,
            )
            installed = self.command_channel.run(command)
            if installed.returncode != 0:
                detail = (installed.stderr or installed.stdout).strip()
                suffix = f": {detail}" if detail else ""
                raise GarDomainError(f"artifact配置に失敗しました (exit {installed.returncode}){suffix}")

        if receipt is not None:
            self._write_deployment(receipt)

    def _write_deployment(self, record: dict) -> None:
        result = self.command_channel.run(remote_deployment_command(record))
        if result.returncode:
            raise GarDomainError(f"Simulation deployment receiptの更新に失敗しました (exit {result.returncode})")

    def configure_system_env(self, application: str, values: Mapping[str, str]) -> str:
        """Atomically install a runtime-owned system environment file."""

        self._validate_system_env(application, values)
        destination = f"/etc/gar/system/{application}.env"
        content = "".join(f"{name}={values[name]}\n" for name in sorted(values))
        with tempfile.TemporaryDirectory(prefix="gar-system-env-") as directory:
            source = Path(directory) / f"{application}.env"
            source.write_text(content, encoding="utf-8")
            staging = f"/tmp/gar-system-env-{os.getpid()}-{application}.env"
            transferred = self.file_channel.push(source, staging)
            if transferred.returncode != 0:
                raise GarDomainError(f"system env転送に失敗しました (exit {transferred.returncode})")
            installed = self.command_channel.run(
                self._install_command(staging, destination, source_is_dir=False, mode="0644")
            )
        if installed.returncode != 0:
            detail = (installed.stderr or installed.stdout).strip()
            suffix = f": {detail}" if detail else ""
            raise GarDomainError(f"system env配置に失敗しました (exit {installed.returncode}){suffix}")
        return destination

    def start(self, hardware: dict[str, list[dict[str, str]]]) -> int:
        return self._run(self.command_builder.build_sim_start(hardware))

    def stop(self, hardware: dict[str, list[dict[str, str]]]) -> int:
        return self._run(self.command_builder.build_sim_stop(hardware))

    def status(self, hardware: dict[str, list[dict[str, str]]]) -> int:
        return self._run(self.command_builder.build_sim_status(hardware))

    def diag(self, hardware: dict[str, list[dict[str, str]]]) -> SimulationDiagnostic:
        result = self.command_channel.run(self.command_builder.build_sim_diag_json(hardware))
        return SimulationDiagnostic.from_command(result)

    def observe(self, hardware, *, diagnostic: bool) -> dict[str, dict[str, object]]:
        result = self.command_channel.run(self.command_builder.build_component_status(hardware))
        connection = component("reachable", True)
        if result.returncode:
            error = result.stderr.strip() or f"service observation failed (exit {result.returncode})"
            return {
                "connection": connection,
                "runtime": component("unknown", False, error=error),
                "app": component("unknown", False, error=error),
            }
        try:
            services = json.loads(result.stdout)
            if (
                not isinstance(services, dict)
                or "gar-sim-app.service" not in services
                or any(not isinstance(value, dict) for value in services.values())
            ):
                raise ValueError("service observationの形式が不正です")
        except ValueError as error:
            return {
                "connection": connection,
                "runtime": component("unknown", False, error=str(error)),
                "app": component("unknown", False, error=str(error)),
            }
        app = services.pop("gar-sim-app.service")
        running = bool(services) and all(
            value.get("loaded") is True and value.get("active") is True and value.get("exit_code") == 0
            for value in services.values()
        )
        runtime = component("running" if running else "stopped", running, services=services)
        if diagnostic:
            report = self.diag(hardware)
            runtime["diagnostic"] = report.to_payload()
            runtime["ok"] = running and report.exit_code == 0
            if running and not runtime["ok"]:
                runtime["state"] = "degraded"
        application_running = (
            app.get("loaded") is True
            and app.get("active") is True
            and app.get("exit_code") == 0
            and app.get("placeholder") is False
        )
        application = component(
            "running" if application_running else "not_deployed" if app.get("placeholder") else "stopped",
            application_running,
            verification="service_state",
        )
        application.update(app.get("identity", {"build_id_verification": "unknown", "build_id_match": False}))
        application["ok"] = application_running and application.get("build_id_match") is True
        return {"connection": connection, "runtime": runtime, "app": application}

    def log(self) -> int:
        return self._run(self.command_builder.build_sim_log())

    def _run(self, command: str) -> int:
        result = self.command_channel.run(command)
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.stderr:
            print(
                result.stderr,
                end="" if result.stderr.endswith("\n") else "\n",
                file=sys.stderr,
            )
        return result.returncode

    def _destination(self, destination: str) -> str:
        mapped = self._DESTINATIONS.get(destination)
        if mapped:
            return mapped
        if destination.startswith("~/web-bridge/"):
            return "/usr/local/lib/gar/web-bridge/" + destination.removeprefix("~/web-bridge/")
        return destination

    @classmethod
    def _validate_system_env(cls, application: str, values: Mapping[str, str]) -> None:
        if not isinstance(application, str) or not cls._SAFE_APPLICATION.fullmatch(application):
            raise GarDomainError(f"system env application名が不正です: {application!r}")
        for name, value in values.items():
            if not isinstance(name, str) or not cls._SAFE_ENV_NAME.fullmatch(name):
                raise GarDomainError(f"system env名が不正です: {name!r}")
            if not isinstance(value, str) or "\x00" in value or "\n" in value or "\r" in value:
                raise GarDomainError(f"system env値に改行またはNULは使えません: {name}")

    @staticmethod
    def _install_command(staging: str, destination: str, *, source_is_dir: bool, mode: str | None) -> str:
        staging_expr = shlex.quote(staging)
        if destination == "~":
            destination_expr = '"${HOME}"'
        elif destination.startswith("~/"):
            destination_expr = f'"${{HOME}}"/{shlex.quote(destination[2:])}'
        else:
            destination_expr = shlex.quote(destination)

        sudo = "" if destination.startswith("~") else "sudo "
        cleanup_command = shlex.quote(f"rm -rf -- {staging_expr}")
        commands = [
            "set -eu",
            f"trap {cleanup_command} EXIT",
            f"{sudo}mkdir -p $(dirname {destination_expr})",
        ]
        if source_is_dir:
            commands.extend(
                [
                    f"{sudo}mkdir -p {destination_expr}",
                    f"{sudo}cp -a {staging_expr}/. {destination_expr}/",
                ]
            )
        else:
            temporary_expr = shlex.quote(f"{destination}.gar-new")
            commands.append(f"{sudo}cp {staging_expr} {temporary_expr}")
            if mode:
                commands.append(f"{sudo}chmod {shlex.quote(mode)} {temporary_expr}")
            commands.append(f"{sudo}mv -f {temporary_expr} {destination_expr}")
        if mode and source_is_dir:
            commands.append(f"{sudo}chmod {shlex.quote(mode)} {destination_expr}")
        return "\n".join(commands)
