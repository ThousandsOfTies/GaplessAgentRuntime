"""Target manifest discovery for GAR setup."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.gar_lib._config import PROJECT_ROOT

DEFAULT_GAR_TOOLS_REPO = "https://github.com/ThousandsOfTies/gar-tools"


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

    return gar_tools_root() / "targets"


def gar_tools_root() -> Path:
    existing = find_gar_tools_root()
    if existing is not None:
        return existing
    return PROJECT_ROOT / ".gar" / "tools"


def find_gar_tools_root() -> Path | None:
    for candidate in gar_tools_root_candidates():
        if (candidate / "targets").is_dir():
            return candidate
    return None


def gar_tools_root_candidates() -> list[Path]:
    raw = os.environ.get("GAR_TOOLS_ROOT")
    candidates: list[Path] = []
    if raw:
        candidates.append(Path(raw).expanduser())

    candidates.extend(
        [
            PROJECT_ROOT / "gar-tools",
            PROJECT_ROOT / ".gar" / "tools",
            PROJECT_ROOT.parent / "gar-tools",
        ]
    )

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def ensure_gar_tools_available(*, auto_clone: bool = True) -> Path | None:
    existing = find_gar_tools_root()
    if existing is not None:
        return existing
    if not auto_clone:
        return None

    dest = PROJECT_ROOT / ".gar" / "tools"
    repo = os.environ.get("GAR_TOOLS_REPO", DEFAULT_GAR_TOOLS_REPO)
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["git", "clone", "--depth", "1", repo, str(dest)], check=False)
    if result.returncode != 0:
        return None
    return dest


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
