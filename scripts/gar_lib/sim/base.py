"""Simulation target abstraction interfaces."""
from __future__ import annotations

from abc import ABC, abstractmethod


class SimCommandBuilder(ABC):
    """Generates target-specific commands for simulation operations."""

    @abstractmethod
    def build_gpio_systemd_install(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str: ...
    @abstractmethod
    def build_sim_diag_json(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str: ...
    @abstractmethod
    def build_gpio_sim_setup(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str: ...
    @abstractmethod
    def build_gpio_sim_teardown(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str: ...
    @abstractmethod
    def build_systemd_install(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str: ...
    @abstractmethod
    def build_systemd_start(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str: ...
    @abstractmethod
    def build_systemd_stop(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str: ...
    @abstractmethod
    def build_sim_start(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str: ...
    @abstractmethod
    def build_sim_stop(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str: ...
    @abstractmethod
    def build_sim_status(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str: ...
    @abstractmethod
    def build_sim_log(self) -> str: ...
    @abstractmethod
    def build_gpio_runtime_status(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str: ...
    @abstractmethod
    def build_panel(self, action: str, params: dict) -> str: ...


class SimEnvProcessor:
    """High-level ``gar sim env`` operations on a target device.

    Mirrors :class:`~scripts.gar_lib.environments.base.DevEnvironment`: every
    verb has a default implementation here that raises ``NotImplementedError``
    with a message explaining what is missing. Concrete providers (Wokwi,
    Linux systemd, ...) override only the verbs they actually support; callers
    catch ``NotImplementedError`` to show ``gar setup`` guidance instead of a
    bare traceback.
    """

    def start(self, hw_definition: dict[str, list[dict[str, str]]]) -> int:
        raise NotImplementedError(f"{type(self).__name__} does not implement start")

    def stop(self, hw_definition: dict[str, list[dict[str, str]]]) -> int:
        raise NotImplementedError(f"{type(self).__name__} does not implement stop")

    def status(self, hw_definition: dict[str, list[dict[str, str]]], json_output: bool = False) -> int:
        raise NotImplementedError(f"{type(self).__name__} does not implement status")

    def log(self) -> int:
        raise NotImplementedError(f"{type(self).__name__} does not implement log")

    def diag_json(self, hw_definition: dict[str, list[dict[str, str]]]) -> int:
        raise NotImplementedError(f"{type(self).__name__} does not implement diag_json")

    def gpio_sim_check(self, json_output: bool = False) -> int:
        raise NotImplementedError(f"{type(self).__name__} does not implement gpio_sim_check")

    def gpio_command(self, command: str, hw_definition: dict[str, list[dict[str, str]]], json_output: bool = False) -> int:
        raise NotImplementedError(f"{type(self).__name__} does not implement gpio_command")

    def panel(self, action: str, params: dict, json_output: bool = False) -> int:
        raise NotImplementedError(f"{type(self).__name__} does not implement panel")

    def build(self, *, json_output: bool = False) -> int:
        raise NotImplementedError(f"{type(self).__name__} does not implement build")
