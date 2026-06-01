"""`agp sim deploy` / `agp native deploy`: artifact manifest deploy."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from scripts.agp_lib._config import (
    PROJECT_ROOT,
    default_ec2_host,
    load_config,
)


def run_deploy_command(
    target: str,
    *,
    artifacts_dir: str | None = None,
    host: str | None = None,
    serial: str | None = None,
    dest: str = "/home/user",
) -> int:
    root = Path(artifacts_dir).expanduser() if artifacts_dir else default_artifacts_dir()
    root = root.resolve()

    if target == "sim":
        return deploy_sim_artifacts(root, host=host)
    if target == "native":
        provider_id = selected_device_provider_id(load_config())
        if provider_id == "ssh_scp":
            if not host:
                print(
                    "agp native deploy: SSH/scp provider requires --host",
                    file=sys.stderr,
                )
                return 1
            return deploy_native_artifacts_ssh(root, host=host, dest=dest)
        return deploy_native_artifacts(root, serial=serial, dest=dest)

    print(f"unknown deploy target: {target}", file=sys.stderr)
    return 1


def selected_device_provider_id(config: dict) -> str | None:
    selected = config.get("selected_providers")
    if isinstance(selected, dict):
        value = selected.get("device")
        if isinstance(value, str) and value:
            return value
    return None


def default_artifacts_dir() -> Path:
    return PROJECT_ROOT.parent / "agp-build-env" / "artifacts" / "from-codespace"


def find_artifact_manifest(root: Path) -> Path | None:
    direct = root / "artifact.json"
    if direct.exists():
        return direct

    candidates = sorted(path for path in root.iterdir() if (path / "artifact.json").exists()) if root.exists() else []
    if len(candidates) == 1:
        return candidates[0] / "artifact.json"
    return None


def load_artifact_manifest(root: Path) -> tuple[Path, dict] | None:
    manifest_path = find_artifact_manifest(root)
    if manifest_path is None:
        print(f"missing artifact manifest: {root / 'artifact.json'}", file=sys.stderr)
        return None

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"invalid artifact manifest JSON: {manifest_path}: {exc}", file=sys.stderr)
        return None

    if not isinstance(data, dict):
        print(f"invalid artifact manifest: root must be an object: {manifest_path}", file=sys.stderr)
        return None

    return manifest_path.parent, data


def artifact_deploy_files(manifest: dict, target: str) -> list[dict] | None:
    deploy = manifest.get("deploy")
    if not isinstance(deploy, dict):
        print("invalid artifact manifest: deploy must be an object", file=sys.stderr)
        return None

    target_config = deploy.get(target)
    if not isinstance(target_config, dict):
        print(f"artifact manifest has no deploy.{target} section", file=sys.stderr)
        return None

    files = target_config.get("files")
    if not isinstance(files, list) or not files:
        print(f"artifact manifest deploy.{target}.files must be a non-empty list", file=sys.stderr)
        return None

    for index, entry in enumerate(files):
        if not isinstance(entry, dict):
            print(f"artifact manifest deploy.{target}.files[{index}] must be an object", file=sys.stderr)
            return None
        if not isinstance(entry.get("src"), str) or not isinstance(entry.get("dest"), str):
            print(
                f"artifact manifest deploy.{target}.files[{index}] requires string src and dest",
                file=sys.stderr,
            )
            return None
        mode = entry.get("mode")
        if mode is not None and not (isinstance(mode, str) and re.fullmatch(r"[0-7]{3,4}", mode)):
            print(
                f"artifact manifest deploy.{target}.files[{index}].mode must match [0-7]{{3,4}}",
                file=sys.stderr,
            )
            return None

    return files


def resolve_artifact_src(bundle_root: Path, src: str) -> Path | None:
    source = (bundle_root / src).resolve()
    try:
        source.relative_to(bundle_root)
    except ValueError:
        print(f"artifact src escapes bundle root: {src}", file=sys.stderr)
        return None

    if not source.exists():
        print(f"missing artifact: {source}", file=sys.stderr)
        return None

    return source


def load_deploy_files(root: Path, target: str) -> tuple[Path, list[dict]] | None:
    loaded = load_artifact_manifest(root)
    if loaded is None:
        return None

    bundle_root, manifest = loaded
    files = artifact_deploy_files(manifest, target)
    if files is None:
        return None

    return bundle_root, files


def native_dest_path(manifest_dest: str, base_dest: str) -> str:
    if manifest_dest.startswith(("/", "~")):
        return manifest_dest
    return f"{base_dest.rstrip('/')}/{manifest_dest}"


def deploy_sim_artifacts(root: Path, *, host: str | None) -> int:
    resolved_host = host or default_ec2_host(load_config())
    loaded = load_deploy_files(root, "sim")
    if loaded is None:
        return 1

    bundle_root, files = loaded
    for entry in files:
        source = resolve_artifact_src(bundle_root, entry["src"])
        if source is None:
            return 1

        command = ["scp", "-F", str(Path.home() / ".ssh" / "config")]
        if source.is_dir():
            command.append("-r")
        command.extend([str(source), f"{resolved_host}:{entry['dest']}"])
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            return result.returncode

        mode = entry.get("mode")
        if isinstance(mode, str):
            result = subprocess.run(
                ["ssh", "-F", str(Path.home() / ".ssh" / "config"), resolved_host, "chmod", mode, entry["dest"]],
                check=False,
            )
            if result.returncode != 0:
                return result.returncode

    return 0


def deploy_native_artifacts(root: Path, *, serial: str | None, dest: str) -> int:
    loaded = load_deploy_files(root, "native")
    if loaded is None:
        return 1

    bundle_root, files = loaded
    for entry in files:
        source = resolve_artifact_src(bundle_root, entry["src"])
        if source is None:
            return 1

        target_dest = native_dest_path(entry["dest"], dest)
        command = ["adb"]
        if serial:
            command.extend(["-s", serial])
        command.extend(["push", str(source), target_dest])
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            return result.returncode

        mode = entry.get("mode")
        if isinstance(mode, str):
            command = ["adb"]
            if serial:
                command.extend(["-s", serial])
            command.extend(["shell", "chmod", mode, target_dest])
            result = subprocess.run(command, check=False)
            if result.returncode != 0:
                return result.returncode

    return 0


def deploy_native_artifacts_ssh(root: Path, *, host: str, dest: str) -> int:
    loaded = load_deploy_files(root, "native")
    if loaded is None:
        return 1

    bundle_root, files = loaded
    ssh_config = str(Path.home() / ".ssh" / "config")
    for entry in files:
        source = resolve_artifact_src(bundle_root, entry["src"])
        if source is None:
            return 1

        target_dest = native_dest_path(entry["dest"], dest)
        command = ["scp", "-F", ssh_config]
        if source.is_dir():
            command.append("-r")
        command.extend([str(source), f"{host}:{target_dest}"])
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            return result.returncode

        mode = entry.get("mode")
        if isinstance(mode, str):
            result = subprocess.run(
                ["ssh", "-F", ssh_config, host, "chmod", mode, target_dest],
                check=False,
            )
            if result.returncode != 0:
                return result.returncode

    return 0
