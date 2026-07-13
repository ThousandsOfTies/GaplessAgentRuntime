"""Linux/systemd simulation runtime composed with capability channels."""

from __future__ import annotations

import os
import shlex

from scripts.gar_lib.access.base import CommandChannel, FileChannel
from scripts.gar_lib.artifacts.manifest import load_deploy_files, resolve_artifact_src
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.simulation.base import SimCommandBuilder
from scripts.gar_lib.simulation.diagnostic import SimulationDiagnostic


class LinuxSystemdSimulationEnvironment:
    _SECTIONS = {
        ArtifactKind.SIM_APP: "app",
        ArtifactKind.SIM_RUNTIME: "sim_env",
    }
    _DESTINATIONS = {
        "~/cuse_i2c": "/usr/local/sbin/cuse_i2c",
        "~/cuse_spi": "/usr/local/sbin/cuse_spi",
        "~/web-bridge": "/usr/local/lib/gar/web-bridge",
    }

    def __init__(
        self,
        command_channel: CommandChannel,
        file_channel: FileChannel,
        command_builder: SimCommandBuilder,
    ):
        self.command_channel = command_channel
        self.file_channel = file_channel
        self.command_builder = command_builder

    def deploy(self, artifact: Artifact) -> None:
        section = self._SECTIONS.get(artifact.kind)
        if section is None:
            raise GarDomainError(f"Linux simulationへ配置できないartifactです: {artifact.kind.value}")
        loaded = load_deploy_files(artifact.bundle_path, section)
        if loaded is None:
            raise GarDomainError(f"artifact manifestを読み込めません: {artifact.bundle_path}")
        bundle_root, files = loaded

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
                raise GarDomainError(f"artifact配置に失敗しました (exit {installed.returncode})")

    def start(self, hardware: dict[str, list[dict[str, str]]]) -> int:
        return self._run(self.command_builder.build_sim_start(hardware))

    def stop(self, hardware: dict[str, list[dict[str, str]]]) -> int:
        return self._run(self.command_builder.build_sim_stop(hardware))

    def status(self, hardware: dict[str, list[dict[str, str]]]) -> int:
        return self._run(self.command_builder.build_sim_status(hardware))

    def diag(self, hardware: dict[str, list[dict[str, str]]]) -> SimulationDiagnostic:
        result = self.command_channel.run(self.command_builder.build_sim_diag_json(hardware))
        return SimulationDiagnostic.from_command(result)

    def log(self) -> int:
        return self._run(self.command_builder.build_sim_log())

    def _run(self, command: str) -> int:
        result = self.command_channel.run(command)
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.stderr:
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
        return result.returncode

    def _destination(self, destination: str) -> str:
        mapped = self._DESTINATIONS.get(destination)
        if mapped:
            return mapped
        if destination.startswith("~/web-bridge/"):
            return "/usr/local/lib/gar/web-bridge/" + destination.removeprefix("~/web-bridge/")
        return destination

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
        commands = [f"{sudo}mkdir -p $(dirname {destination_expr})"]
        if source_is_dir:
            commands.extend(
                [
                    f"{sudo}mkdir -p {destination_expr}",
                    f"{sudo}cp -a {staging_expr}/. {destination_expr}/",
                ]
            )
        else:
            commands.append(f"{sudo}cp {staging_expr} {destination_expr}")
        if mode:
            commands.append(f"{sudo}chmod {shlex.quote(mode)} {destination_expr}")
        return "; ".join(commands)
