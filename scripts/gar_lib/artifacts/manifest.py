"""``artifact.json`` manifest parsing, Codespace fetch, and provider resolution.

Shared by simulation and target environment deploy operations and explicit
artifact fetch commands.

artifact.json スキーマ:
  deploy.app     — target app バイナリ（VM ・実機共通）
  deploy.sim_env — VM 専用環境インフラ（CUSE stubs / web-bridge）
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.gar_lib.access.codespaces import select_codespace_from_list
from scripts.gar_lib.config import PROJECT_ROOT

DEFAULT_CODESPACE_ARTIFACT_ROOT = "/workspaces/gar-build-env/artifacts/from-codespace"


def default_artifacts_dir() -> Path:
    return PROJECT_ROOT.parent / "gar-build-env" / "artifacts" / "from-codespace"


def default_codespace_artifact_root() -> str:
    return os.environ.get("GAR_CODESPACE_ARTIFACT_ROOT", DEFAULT_CODESPACE_ARTIFACT_ROOT)


def select_codespace(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    env_value = os.environ.get("GAR_CODESPACE_NAME") or os.environ.get("CODESPACE_NAME")
    if env_value:
        return env_value

    result = subprocess.run(
        ["gh", "codespace", "list"],
        check=False,
        capture_output=True,
        text=True,
        env=gh_env(),
    )
    if result.returncode != 0:
        print("gar target fetch: failed to list Codespaces", file=sys.stderr)
        if result.stderr:
            print(result.stderr.strip(), file=sys.stderr)
        return None
    return select_codespace_from_list(result.stdout)


def gh_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("GH_PROMPT_DISABLED", "1")
    return env


def artifact_manifest_deploy_sources(manifest: dict) -> list[str] | None:
    deploy = manifest.get("deploy")
    if not isinstance(deploy, dict):
        print("invalid artifact manifest: deploy must be an object", file=sys.stderr)
        return None

    sources: list[str] = []
    seen: set[str] = set()
    for target, target_config in deploy.items():
        if not isinstance(target, str) or not isinstance(target_config, dict):
            print("invalid artifact manifest: deploy targets must be objects", file=sys.stderr)
            return None
        files = artifact_deploy_files(manifest, target)
        if files is None:
            return None
        for entry in files:
            src = entry["src"]
            if src not in seen:
                seen.add(src)
                sources.append(src)
    return sources


def fetch_codespace_artifacts(
    root: Path,
    *,
    codespace: str | None = None,
    remote_root: str | None = None,
) -> int:
    selected_codespace = select_codespace(codespace)
    if not selected_codespace:
        print("gar target fetch: pass --codespace NAME or set GAR_CODESPACE_NAME", file=sys.stderr)
        return 1

    resolved_remote_root = (remote_root or default_codespace_artifact_root()).rstrip("/")
    root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="gar-artifact-fetch-") as tmp:
        manifest_tmp = Path(tmp) / "artifact.json"
        result = gh_codespace_cp(
            selected_codespace,
            f"{resolved_remote_root}/artifact.json",
            manifest_tmp,
        )
        if result.returncode != 0:
            print(
                f"gar target fetch: failed to fetch {resolved_remote_root}/artifact.json",
                file=sys.stderr,
            )
            return result.returncode

        try:
            manifest = json.loads(manifest_tmp.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"invalid artifact manifest JSON from Codespace: {exc}", file=sys.stderr)
            return 1
        if not isinstance(manifest, dict):
            print("invalid artifact manifest from Codespace: root must be an object", file=sys.stderr)
            return 1

        sources = artifact_manifest_deploy_sources(manifest)
        if sources is None:
            return 1

        for src in sources:
            if src.startswith("/") or ".." in Path(src).parts:
                print(f"artifact src escapes bundle root: {src}", file=sys.stderr)
                return 1
            local_dest = root / src
            local_dest.parent.mkdir(parents=True, exist_ok=True)
            if local_dest.is_dir():
                shutil.rmtree(local_dest)
            elif local_dest.exists():
                local_dest.unlink()
            result = gh_codespace_cp(
                selected_codespace,
                f"{resolved_remote_root}/{src}",
                local_dest,
                recursive=True,
            )
            if result.returncode != 0:
                print(f"gar target fetch: failed to fetch {src}", file=sys.stderr)
                return result.returncode

        (root / "artifact.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(f"Codespace: {selected_codespace}")
    print(f"Artifacts: {root}")
    return 0


def gh_codespace_cp(
    codespace: str,
    remote_path: str,
    local_path: Path,
    *,
    recursive: bool = False,
) -> subprocess.CompletedProcess:
    command = ["gh", "codespace", "cp", "-e", "-c", codespace]
    if recursive:
        command.append("-r")
    command.extend([f"remote:{remote_path}", str(local_path)])
    return subprocess.run(command, check=False, env=gh_env())


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
    """Return deploy files for *target* section."""
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


def target_dest_path(manifest_dest: str, base_dest: str) -> str:
    if manifest_dest.startswith(("/", "~")):
        return manifest_dest
    return f"{base_dest.rstrip('/')}/{manifest_dest}"
