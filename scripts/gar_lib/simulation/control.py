"""Simulation hardware control plane independent from transport details."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from scripts.gar_lib.access.base import CommandChannel, CommandResult
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.simulation.linux import LinuxSystemdCommandBuilder, gpio_sim_plan
from scripts.gar_lib.simulation.parse import parse_gpio_runtime_status, parse_gpio_sim_check


@dataclass(frozen=True)
class HardwareControlResult:
    exit_code: int
    payload: dict[str, object] | None = None
    stdout: str = ""
    stderr: str = ""

    def render(self, *, json_output: bool) -> None:
        if json_output and self.payload is not None:
            print(json.dumps(self.payload, ensure_ascii=False, indent=2))
            return
        if self.stdout:
            print(self.stdout, end="" if self.stdout.endswith("\n") else "\n")
        if self.stderr:
            print(self.stderr, end="" if self.stderr.endswith("\n") else "\n")
        if self.payload is not None and not self.stdout:
            for key, value in self.payload.items():
                print(f"{key}: {value}")


class SimulationHardwareControl(Protocol):
    def gpio(
        self,
        action: str,
        hardware: dict[str, list[dict[str, str]]],
    ) -> HardwareControlResult: ...

    def panel(self, action: str, params: dict[str, object]) -> HardwareControlResult: ...


class SimulationHardwareControlResolver(Protocol):
    def for_workspace(self, workspace: Workspace) -> SimulationHardwareControl: ...


class LinuxBridgeHardwareControl:
    def __init__(
        self,
        command_channel: CommandChannel,
        command_builder: LinuxSystemdCommandBuilder,
        *,
        host: str | None = None,
    ):
        self.command_channel = command_channel
        self.command_builder = command_builder
        self.host = host

    def gpio(
        self,
        action: str,
        hardware: dict[str, list[dict[str, str]]],
    ) -> HardwareControlResult:
        if action == "plan":
            return HardwareControlResult(0, self._with_host(gpio_sim_plan(hardware)))
        if action == "install":
            return self._command(self.command_builder.build_gpio_systemd_install(hardware))
        if action == "start":
            command = (
                self.command_builder.build_gpio_systemd_install(hardware)
                + "; sudo systemctl restart gar-gpio-sim.service; "
                "sudo systemctl --no-pager --full status gar-gpio-sim.service"
            )
            return self._command(command)
        if action == "stop":
            return self._command("sudo systemctl stop gar-gpio-sim.service")
        if action == "status":
            result = self.command_channel.run(
                self.command_builder.build_gpio_runtime_status(hardware)
            )
            payload = (
                parse_gpio_runtime_status(result.stdout)
                if result.returncode == 0
                else self._error_payload(result)
            )
            return HardwareControlResult(
                result.returncode if result.returncode else (0 if payload.get("ok") else 1),
                self._with_host(payload),
                result.stdout,
                result.stderr,
            )
        if action == "check":
            result = self.command_channel.run(self.command_builder.build_gpio_sim_check())
            payload = (
                parse_gpio_sim_check(result.stdout)
                if result.returncode == 0
                else self._error_payload(result)
            )
            return HardwareControlResult(
                result.returncode if result.returncode else (0 if payload.get("ok") else 1),
                self._with_host(payload),
                result.stdout,
                result.stderr,
            )
        return HardwareControlResult(1, {"ok": False, "error": f"unknown gpio action: {action}"})

    def panel(self, action: str, params: dict[str, object]) -> HardwareControlResult:
        result = self.command_channel.run(self.command_builder.build_panel(action, params))
        if action != "state":
            return HardwareControlResult(result.returncode, stdout=result.stdout, stderr=result.stderr)
        try:
            payload = json.loads(result.stdout) if result.stdout.strip() else {}
        except json.JSONDecodeError:
            payload = {"ok": False, "raw": result.stdout.strip()}
        if not isinstance(payload, dict):
            payload = {"ok": False, "state": payload}
        return HardwareControlResult(result.returncode, payload, result.stdout, result.stderr)

    def _command(self, command: str) -> HardwareControlResult:
        result = self.command_channel.run(command)
        return HardwareControlResult(result.returncode, stdout=result.stdout, stderr=result.stderr)

    def _with_host(self, payload: dict) -> dict[str, object]:
        return {**payload, **({"host": self.host} if self.host else {})}

    @staticmethod
    def _error_payload(result: CommandResult) -> dict[str, object]:
        return {
            "ok": False,
            "error": f"command exited {result.returncode}",
            "stderr": result.stderr.strip(),
        }
