"""Product workspace model."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.gar_lib.core.errors import GarDomainError


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str
    branch: str
    connection: Mapping[str, Any]
    selected_environments: Mapping[str, str] = field(default_factory=dict)
    ec2: Mapping[str, Any] = field(default_factory=dict)

    @property
    def connection_type(self) -> str:
        value = self.connection.get("type")
        return value if isinstance(value, str) else ""

    @property
    def local_root(self) -> Path:
        if self.connection_type != "local":
            raise GarDomainError(f"workspace は local 接続ではありません: {self.name}")
        value = self.connection.get("path")
        if not isinstance(value, str) or not value:
            raise GarDomainError(f"workspace の local path が未設定です: {self.name}")
        return Path(value).expanduser().resolve()

    @property
    def remote_root(self) -> str:
        value = self.connection.get("path")
        if not isinstance(value, str) or not value:
            raise GarDomainError(f"workspace の remote path が未設定です: {self.name}")
        return value.rstrip("/")

    @property
    def codespace_name(self) -> str:
        if self.connection_type != "codespaces":
            raise GarDomainError(f"workspace は Codespaces 接続ではありません: {self.name}")
        value = self.connection.get("codespace")
        if not isinstance(value, str) or not value:
            raise GarDomainError(f"workspace の Codespaces 名が未設定です: {self.name}")
        return value
