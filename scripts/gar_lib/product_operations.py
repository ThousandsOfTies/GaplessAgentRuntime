"""Product-owned operation manifests and a command-independent process runner."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.operation_process import run_bounded

MANIFEST = "gar-operations.json"
_NAME = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")


@dataclass(frozen=True)
class Operation:
    name: str
    description: str
    entrypoint: Path
    runtime: str
    arguments: tuple[str, ...]
    timeout: int
    result_format: str
    result_fields: tuple[str, ...]
    python: Path | None = None


@dataclass(frozen=True)
class Operations:
    root: Path
    operations: dict[str, Operation]
    aliases: dict[tuple[str, ...], str]


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def load_operations(root: Path) -> Operations:
    root = root.resolve()
    path = root / MANIFEST
    if not path.is_file():
        raise GarDomainError(f"{MANIFEST} がありません。Productに操作を定義してください")
    try:
        if path.stat().st_size > 262144:
            raise ValueError("manifest too large")
        spec = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        if not isinstance(spec, dict) or type(spec.get("schema_version")) is not int or spec["schema_version"] != 1:
            raise ValueError("invalid schema")
        if set(spec) - {"schema_version", "operations", "aliases"}:
            raise ValueError("unknown manifest field")
        entries = spec["operations"]
        if not isinstance(entries, dict) or not 1 <= len(entries) <= 128:
            raise ValueError("invalid operations")
        operations = {}
        for name, entry in entries.items():
            if not _NAME.fullmatch(name) or not isinstance(entry, dict):
                raise ValueError("invalid operation")
            if set(entry) - {
                "python",
                "description",
                "entrypoint",
                "runtime",
                "args",
                "timeout_seconds",
                "result",
                "result_fields",
            }:
                raise ValueError("unknown operation field")
            entry_text = entry["entrypoint"]
            if not isinstance(entry_text, str):
                raise ValueError("invalid entrypoint")
            relative = Path(entry_text)
            target = (root / relative).resolve()
            runtime = entry.get("runtime", "python")
            extensions = {"python": (".py",), "node": (".js", ".cjs", ".mjs")}
            if (
                relative.is_absolute()
                or relative.drive
                or ".." in relative.parts
                or "\\" in entry_text
                or ":" in entry_text
                or not target.is_relative_to(root)
                or not target.is_file()
                or runtime not in extensions
                or target.suffix not in extensions[runtime]
            ):
                raise ValueError("invalid entrypoint")
            python = None
            if "python" in entry:
                interpreter = entry["python"]
                if not isinstance(interpreter, str) or runtime != "python":
                    raise ValueError("invalid python environment")
                relative_python = Path(interpreter)
                python = (root / relative_python).absolute()
                if (
                    relative_python.is_absolute()
                    or relative_python.drive
                    or ".." in relative_python.parts
                    or "\\" in interpreter
                    or ":" in interpreter
                    or not python.is_relative_to(root)
                    or not python.is_file()
                ):
                    raise ValueError("invalid python environment")
            args = entry.get("args", [])
            if (
                not isinstance(args, list)
                or len(args) > 128
                or any(not isinstance(arg, str) or "\0" in arg for arg in args)
            ):
                raise ValueError("invalid arguments")
            timeout = entry.get("timeout_seconds", 90)
            if type(timeout) is not int or not 1 <= timeout <= 3600:
                raise ValueError("invalid timeout")
            description = entry.get("description", "")
            if not isinstance(description, str) or len(description) > 500:
                raise ValueError("invalid description")
            output = entry.get("result", "json")
            fields = entry.get("result_fields", ["ok", "state", "error"])
            if (
                output not in ("json", "text")
                or not isinstance(fields, list)
                or any(not isinstance(field, str) or not _FIELD.fullmatch(field) for field in fields)
            ):
                raise ValueError("invalid result contract")
            operations[name] = Operation(
                name, description, target, runtime, tuple(args), timeout, output, tuple(fields), python
            )
        raw_aliases = spec.get("aliases", {})
        if not isinstance(raw_aliases, dict) or len(raw_aliases) > 128:
            raise ValueError("invalid aliases")
        aliases = {}
        for name, operation in raw_aliases.items():
            tokens = tuple(name.split(" "))
            if (
                not 1 <= len(tokens) <= 2
                or any(not _NAME.fullmatch(token) for token in tokens)
                or operation not in operations
            ):
                raise ValueError("invalid alias")
            if any(tokens[: len(other)] == other or other[: len(tokens)] == tokens for other in aliases):
                raise ValueError("ambiguous alias prefix")
            aliases[tokens] = operation
        return Operations(root, operations, aliases)
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise GarDomainError(f"{MANIFEST} の定義が不正です（操作・入口・Aliasを確認してください）") from error


def execute_operation(
    registry: Operations, name: str, arguments: list[str], workspace: str, *, help_mode: bool = False
) -> dict:
    if name not in registry.operations:
        raise GarDomainError(f"Productに操作がありません: {name}。gar product list で確認してください")
    operation = registry.operations[name]
    executable = str(operation.python or sys.executable) if operation.runtime == "python" else shutil.which("node")
    if not executable:
        raise GarDomainError("Product操作に必要なNode.jsがありません")
    if any("\0" in argument for argument in arguments):
        raise GarDomainError("Product操作の引数が不正です")
    environment = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "GAR_PRODUCT_ROOT": str(registry.root),
        "GAR_PRODUCT_OPERATION": name,
        "GAR_PRODUCT_WORKSPACE": workspace,
    }
    try:
        result = run_bounded(
            [executable, str(operation.entrypoint), *operation.arguments, *arguments],
            cwd=registry.root,
            env=environment,
            timeout=operation.timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise GarDomainError(f"Product操作がタイムアウトしました: {name} ({operation.timeout}秒)") from error
    except OSError as error:
        raise GarDomainError(f"Product操作を起動できませんでした: {name}") from error
    # Arbitrary stderr, command lines and malformed output may contain secrets.
    # Only explicitly declared JSON fields cross the structured result boundary.
    if len(result.stdout.encode("utf-8")) > 1048576:
        raise GarDomainError(f"Product操作の出力が上限を超えました: {name}")
    if operation.result_format == "text" or help_mode:
        payload = {"output": result.stdout} if result.returncode == 0 else {"error": "Product operation failed"}
    else:
        try:
            value = json.loads(result.stdout)
            if not isinstance(value, dict) or ("ok" in value and type(value["ok"]) is not bool):
                raise ValueError("expected object")
        except ValueError as error:
            raise GarDomainError(f"Product操作が有効なJSONを返しませんでした: {name}") from error
        payload = {field: value[field] for field in operation.result_fields if field in value}
        if value.get("ok") is False and result.returncode == 0:
            result.returncode = 1
    code = result.returncode if 0 <= result.returncode <= 255 else 1
    return {"operation": name, "result": payload, "ok": code == 0, "exit_code": code}
