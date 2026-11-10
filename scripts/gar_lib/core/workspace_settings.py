"""Typed settings carried by a resolved product workspace."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Self


class SettingsMapping(Mapping[str, Any]):
    """Small compatibility mapping around explicitly named settings fields."""

    field_names: ClassVar[tuple[str, ...]] = ()

    def __getitem__(self, key: str) -> Any:
        if key not in self.field_names:
            raise KeyError(key)
        value = getattr(self, key)
        if value is None:
            raise KeyError(key)
        return value

    def __iter__(self) -> Iterator[str]:
        return (name for name in self.field_names if getattr(self, name) is not None)

    def __len__(self) -> int:
        return sum(getattr(self, name) is not None for name in self.field_names)

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self}


def _string(settings: Mapping[str, Any], name: str) -> str | None:
    value = settings.get(name)
    return value if isinstance(value, str) and value else None


@dataclass(frozen=True)
class WorkspaceConnection(SettingsMapping):
    type: str
    path: str
    codespace: str | None = None
    host: str | None = None

    field_names = ("type", "path", "codespace", "host")

    @classmethod
    def from_value(cls, value: WorkspaceConnection | Mapping[str, Any]) -> Self:
        if isinstance(value, cls):
            return value
        return cls(
            type=_string(value, "type") or "",
            path=_string(value, "path") or "",
            codespace=_string(value, "codespace"),
            host=_string(value, "host"),
        )


@dataclass(frozen=True)
class SelectedEnvironments(SettingsMapping):
    codespace: str | None = None
    simulator: str | None = None
    simulation_host: str | None = None
    target: str | None = None

    field_names = ("codespace", "simulator", "simulation_host", "target")

    @classmethod
    def from_value(cls, value: SelectedEnvironments | Mapping[str, Any]) -> Self:
        if isinstance(value, cls):
            return value
        return cls(
            codespace=_string(value, "codespace"),
            simulator=_string(value, "simulator"),
            simulation_host=_string(value, "simulation_host"),
            target=_string(value, "target"),
        )


@dataclass(frozen=True)
class BuildSettings(SettingsMapping):
    image: str | None = None
    docker_socket: bool = False
    cache: bool = False

    field_names = ("image", "docker_socket", "cache")

    @classmethod
    def from_value(cls, value: BuildSettings | Mapping[str, Any]) -> Self:
        if isinstance(value, cls):
            return value
        raw_socket = value.get("docker_socket")
        raw_cache = value.get("cache")
        return cls(
            image=_string(value, "image"),
            docker_socket=raw_socket if isinstance(raw_socket, bool) else False,
            cache=raw_cache if isinstance(raw_cache, bool) else False,
        )


@dataclass(frozen=True)
class SimulationHostSettings(SettingsMapping):
    provider: str | None = None
    host: str | None = None
    private_ip: str | None = None
    arch: str | None = None
    repo_dir: str | None = None
    bridge_port: int | None = None

    field_names = ("provider", "host", "private_ip", "arch", "repo_dir", "bridge_port")

    @classmethod
    def from_value(cls, value: SimulationHostSettings | Mapping[str, Any]) -> Self:
        if isinstance(value, cls):
            return value
        raw_port = value.get("bridge_port")
        bridge_port = raw_port if isinstance(raw_port, int) and not isinstance(raw_port, bool) else None
        return cls(
            provider=_string(value, "provider"),
            host=_string(value, "host"),
            private_ip=_string(value, "private_ip"),
            arch=_string(value, "arch"),
            repo_dir=_string(value, "repo_dir"),
            bridge_port=bridge_port,
        )


@dataclass(frozen=True)
class VirtualBoxSettings(SettingsMapping):
    vm: str | None = None

    field_names = ("vm",)

    @classmethod
    def from_value(cls, value: VirtualBoxSettings | Mapping[str, Any]) -> Self:
        if isinstance(value, cls):
            return value
        return cls(vm=_string(value, "vm"))


@dataclass(frozen=True)
class Ec2Settings(SettingsMapping):
    host: str | None = None
    instance_id: str | None = None
    private_ip: str | None = None
    region: str | None = None
    repo_dir: str | None = None
    identity_file: str | None = None
    arch: str | None = None

    field_names = ("host", "instance_id", "private_ip", "region", "repo_dir", "identity_file", "arch")

    @classmethod
    def from_value(cls, value: Ec2Settings | Mapping[str, Any]) -> Self:
        if isinstance(value, cls):
            return value
        return cls(**{name: _string(value, name) for name in cls.field_names})


@dataclass(frozen=True)
class DockerSettings(SettingsMapping):
    container: str | None = None
    image: str | None = None
    bridge_port: int | None = None
    repo_dir: str | None = None
    arch: str | None = None

    field_names = ("container", "image", "bridge_port", "repo_dir", "arch")

    @classmethod
    def from_value(cls, value: DockerSettings | Mapping[str, Any]) -> Self:
        if isinstance(value, cls):
            return value
        raw_port = value.get("bridge_port")
        bridge_port = raw_port if isinstance(raw_port, int) and not isinstance(raw_port, bool) else None
        return cls(
            container=_string(value, "container"),
            image=_string(value, "image"),
            bridge_port=bridge_port,
            repo_dir=_string(value, "repo_dir"),
            arch=_string(value, "arch"),
        )


@dataclass(frozen=True)
class TargetSettings(SettingsMapping):
    serial: str | None = None
    dest: str | None = None
    host: str | None = None
    port: str | None = None

    field_names = ("serial", "dest", "host", "port")

    @classmethod
    def from_value(cls, value: TargetSettings | Mapping[str, Any]) -> Self:
        if isinstance(value, cls):
            return value
        return cls(**{name: _string(value, name) for name in cls.field_names})


@dataclass(frozen=True)
class AdbSettings(SettingsMapping):
    exe_path: str | None = None
    version: str | None = None

    field_names = ("exe_path", "version")

    @classmethod
    def from_value(cls, value: AdbSettings | Mapping[str, Any]) -> Self:
        if isinstance(value, cls):
            return value
        return cls(exe_path=_string(value, "exe_path"), version=_string(value, "version"))


@dataclass(frozen=True)
class Esp32Settings(SettingsMapping):
    port: str | None = None

    field_names = ("port",)

    @classmethod
    def from_value(cls, value: Esp32Settings | Mapping[str, Any]) -> Self:
        if isinstance(value, cls):
            return value
        return cls(port=_string(value, "port"))
