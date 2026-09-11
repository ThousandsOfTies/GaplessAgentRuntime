"""Translate a verified artifact snapshot into simulation deployment receipts."""

from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from uuid import uuid4

from scripts.gar_lib.artifacts.manifest import resolve_artifact_src
from scripts.gar_lib.artifacts.metadata import load_artifact_metadata, verify_artifact_checksums
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.simulation.runtime import identity


def deployment_record(root: Path, entries: list, destination: Callable[[str], str | Path]) -> dict:
    metadata = load_artifact_metadata(root)
    record = {"schema_version": 1, "state": "ready", "generation": uuid4().hex, "build_id": None, "files": {}}
    if metadata is None or metadata.is_legacy:
        return record
    verify_artifact_checksums(root, metadata)
    files: dict[str, str] = {}
    for entry in entries:
        source = resolve_artifact_src(root, entry["src"])
        if source is None:
            raise GarDomainError(f"artifact sourceがありません: {entry['src']}")
        target = str(destination(entry["dest"]))
        # Legacy home-relative layouts can still run, but cannot certify an app.
        if not (Path(target).is_absolute() or PurePosixPath(target).is_absolute()):
            return record
        for path in sorted(source.rglob("*")) if source.is_dir() else (source,):
            if not path.is_file():
                continue
            base = PurePosixPath(target) if target.startswith("/") else Path(target)
            name = str(base / path.relative_to(source).as_posix()) if source.is_dir() else target
            if name in files:
                raise GarDomainError(f"artifact配置先が重複しています: {name}")
            files[name] = identity.digest(path)
    return {**record, "build_id": metadata.build_id, "entrypoint": metadata.entrypoint, "files": files}


def remote_identity_command(expression: str, *, sudo: bool = False) -> str:
    source = Path(identity.__file__).read_text(encoding="utf-8")
    return ("sudo " if sudo else "") + "python3 -c " + shlex.quote(source + "\n" + expression)


def remote_deployment_command(record: dict) -> str:
    expression = f"record = json.loads({json.dumps(record)!r})\n"
    if record.get("build_id") and record.get("state") == "ready":
        expression += "assert verified(record), 'deployed app checksum mismatch'\n"
    return remote_identity_command(expression + "write_record(DEPLOYED, record)", sudo=True)
