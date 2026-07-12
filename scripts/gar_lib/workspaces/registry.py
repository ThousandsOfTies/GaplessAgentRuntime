"""Resolve product workspaces from GAR configuration."""

from __future__ import annotations

from typing import Protocol

from scripts.gar_lib.config import load_config, saved_workspaces
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace


class WorkspaceRegistry(Protocol):
    def get(self, selector: str | None) -> Workspace: ...


class ConfigWorkspaceRegistry:
    def get(self, selector: str | None) -> Workspace:
        config = load_config()
        entries = saved_workspaces(config)

        if selector:
            matches = [entry for entry in entries if selector in (entry["id"], entry["name"])]
        elif isinstance(config.get("workspace_id"), str):
            matches = [entry for entry in entries if entry["id"] == config["workspace_id"]]
        elif len(entries) == 1:
            matches = entries
        else:
            matches = []

        if len(matches) != 1:
            available = ", ".join(entry["name"] for entry in entries) or "(なし)"
            raise GarDomainError(f"workspace を一意に選べません。--workspace を指定してください: {available}")

        entry = matches[0]
        environments = entry.get("selected_providers")
        ec2 = entry.get("ec2")
        return Workspace(
            id=entry["id"],
            name=entry["name"],
            branch=entry["branch"],
            connection=dict(entry["connection"]),
            selected_environments=dict(environments) if isinstance(environments, dict) else {},
            ec2=dict(ec2) if isinstance(ec2, dict) else {},
        )
