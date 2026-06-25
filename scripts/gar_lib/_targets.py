"""Target manifest discovery for GAR setup."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.gar_lib._config import PROJECT_ROOT


@dataclass(frozen=True)
class TargetManifest:
    id: str
    display_name: str
    description: str
    tools_root: str
    default_backends: dict[str, str]
    backend_notes: dict[str, str]


def discover_target_manifests() -> list[TargetManifest]:
    targets_root = _targets_root()
    if not targets_root.is_dir():
        return []

    manifests = []
    for path in sorted(targets_root.glob("*/target.json")):
        manifest = _load_target_manifest(path)
        if manifest is not None:
            manifests.append(manifest)
    return manifests


def target_by_id(targets: list[TargetManifest], target_id: str | None) -> TargetManifest | None:
    if target_id is None:
        return None
    for target in targets:
        if target.id == target_id:
            return target
    return None


def _targets_root() -> Path:
    configured = os.environ.get("GAR_TOOLS_TARGETS")
    if configured:
        return Path(configured).expanduser()

    repo_root = os.environ.get("GAR_TOOLS_ROOT")
    if repo_root:
        return Path(repo_root).expanduser() / "targets"

    return PROJECT_ROOT.parent / "gar-tools" / "targets"


def _load_target_manifest(path: Path) -> TargetManifest | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    target_id = _str(data.get("id"))
    display_name = _str(data.get("displayName"))
    description = _str(data.get("description"))
    tools_root = _str(data.get("toolsRoot"))
    if not (target_id and display_name and description and tools_root):
        return None

    return TargetManifest(
        id=target_id,
        display_name=display_name,
        description=description,
        tools_root=tools_root,
        default_backends=_str_dict(data.get("defaultBackends")),
        backend_notes=_str_dict(data.get("backendNotes")),
    )


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _str_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): str(item)
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str)
    }
