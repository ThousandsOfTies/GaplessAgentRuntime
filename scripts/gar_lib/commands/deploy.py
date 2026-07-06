"""`gar sim deploy` / `gar sim env deploy` / `gar target deploy`: artifact manifest deploy.

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

from scripts.gar_lib.commands.code import select_codespace_from_list
from scripts.gar_lib.config import (
    PROJECT_ROOT,
    default_ec2_host,
    load_config,
    saved_esp32_serial_port,
)
from scripts.gar_lib.commands.usb import run_usb_command
from scripts.gar_lib.environments.base import DevEnvironment
from scripts.gar_lib.environments.discovery import discover_environment_providers


def _get_provider(category: str) -> type[DevEnvironment]:
    config = load_config()
    pid = config.get("selected_providers", {}).get(category)
    providers = discover_environment_providers()
    if pid:
        for p in providers:
            if p.provider_id == pid:
                return p
    for p in providers:
        if p.provider_id == ("ssh_remote" if category == "simulation" else "adb_usb"):
            return p
    raise RuntimeError(f"No {category} provider found")


DEFAULT_CODESPACE_ARTIFACT_ROOT = "/workspaces/gar-build-env/artifacts/from-codespace"

SIM_DEST_MAP = {
    "~/cuse_i2c": "/usr/local/sbin/cuse_i2c",
    "~/cuse_spi": "/usr/local/sbin/cuse_spi",
    "~/web-bridge": "/usr/local/lib/gar/web-bridge",
}
SIM_DEST_PREFIX_MAP = {
    "~/web-bridge/": "/usr/local/lib/gar/web-bridge/",
}


def run_deploy_command(
    target: str,
    *,
    artifacts_dir: str | None = None,
    host: str | None = None,
    serial: str | None = None,
    port: str | None = None,
    dest: str = "/home/user",
    codespace: str | None = None,
    remote_root: str | None = None,
) -> int:
    root = Path(artifacts_dir).expanduser() if artifacts_dir else default_artifacts_dir()
    root = root.resolve()

    if target == "sim":
        return deploy_sim_artifacts(root, host=host, section="app")
    if target == "sim_env":
        return deploy_sim_artifacts(root, host=host, section="sim_env")
    if target == "target":
        config = load_config()
        provider_id = selected_target_access_provider_id(config)
        if provider_id == "esp32_esptool":
            from scripts.gar_lib.environments.registry.target_access.esp32_esptool import run_esp32_flash_command

            return run_esp32_flash_command(
                artifact_dir=str(root) if artifacts_dir else None,
                port=port or serial or saved_esp32_serial_port(config),
            )
        if provider_id == "ssh_scp":
            if not host:
                print(
                    "gar target deploy: SSH/scp provider requires --host",
                    file=sys.stderr,
                )
                return 1
        if codespace or remote_root or find_artifact_manifest(root) is None:
            if find_artifact_manifest(root) is None:
                print("gar target deploy: artifact manifest not found; fetching from Codespace", file=sys.stderr)
            result = fetch_codespace_artifacts(
                root,
                codespace=codespace,
                remote_root=remote_root,
            )
            if result != 0:
                return result
        if provider_id == "ssh_scp":
            return deploy_target_artifacts_ssh(root, host=host, dest=dest)
        return deploy_target_artifacts(root, serial=serial, dest=dest)

    print(f"unknown deploy target: {target}", file=sys.stderr)
    return 1


def selected_target_access_provider_id(config: dict) -> str | None:
    selected = config.get("selected_providers")
    if isinstance(selected, dict):
        value = selected.get("target_access")
        if isinstance(value, str) and value:
            return value
    return None


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


def sim_dest_path(manifest_dest: str) -> str:
    mapped = SIM_DEST_MAP.get(manifest_dest)
    if mapped:
        return mapped
    for source_prefix, target_prefix in SIM_DEST_PREFIX_MAP.items():
        if manifest_dest.startswith(source_prefix):
            return target_prefix + manifest_dest.removeprefix(source_prefix)
    return manifest_dest


def shlex_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def remote_path_expr(dest: str) -> str:
    if dest == "~":
        return '"${HOME}"'
    if dest.startswith("~/"):
        return f'"${{HOME}}"/{shlex_quote(dest[2:])}'
    return shlex_quote(dest)


def remote_install_command(staging_path: str, dest: str, *, source_is_dir: bool, mode: str | None) -> str:
    dest_expr = remote_path_expr(dest)
    if dest.startswith("~"):
        commands = [f"mkdir -p $(dirname {dest_expr})"]
        if source_is_dir:
            commands.append(f"mkdir -p {dest_expr}")
            commands.append(f"cp -a {shlex_quote(staging_path)}/. {dest_expr}/")
        else:
            commands.append(f"cp {shlex_quote(staging_path)} {dest_expr}")
        if mode:
            commands.append(f"chmod {shlex_quote(mode)} {dest_expr}")
        return "; ".join(commands)

    commands = [f"sudo mkdir -p $(dirname {dest_expr})"]
    if source_is_dir:
        commands.append(f"sudo mkdir -p {dest_expr}")
        commands.append(f"sudo cp -a {shlex_quote(staging_path)}/. {dest_expr}/")
    else:
        commands.append(f"sudo cp {shlex_quote(staging_path)} {dest_expr}")
    if mode:
        commands.append(f"sudo chmod {shlex_quote(mode)} {dest_expr}")
    return "; ".join(commands)


def deploy_sim_artifacts(root: Path, *, host: str | None, section: str = "app") -> int:
    resolved_host = host or default_ec2_host(load_config())
    loaded = load_deploy_files(root, section)
    if loaded is None:
        return 1

    bundle_root, files = loaded
    provider = _get_provider("simulation")

    for entry in files:
        source = resolve_artifact_src(bundle_root, entry["src"])
        if source is None:
            return 1

        target_dest = sim_dest_path(entry["dest"])
        staging_path = f"/tmp/gar-deploy-{os.getpid()}-{source.name}"

        result = provider.push_file(resolved_host, source, staging_path)
        if result != 0:
            return result

        mode = entry.get("mode")
        install_command = remote_install_command(
            staging_path,
            target_dest,
            source_is_dir=source.is_dir(),
            mode=mode if isinstance(mode, str) else None,
        )
        proc = provider.run_remote(resolved_host, install_command, check=False)
        if proc.returncode != 0:
            return proc.returncode

    return 0


def deploy_target_artifacts(root: Path, *, serial: str | None, dest: str) -> int:
    loaded = load_deploy_files(root, "app")
    if loaded is None:
        return 1

    provider = _get_provider("target_access")
    target = serial if serial else ""
    if provider.provider_id == "adb_usb":
        result = ensure_adb_device(serial=serial)
        if result != 0:
            return result
    elif provider.provider_id == "adb_win":
        # TODO(外形ゆえの暫定): adb_win 経路（方式2）の利用手順を docs に追記する
        # （docs/08_DEVELOPMENT_ENVIRONMENT_POLICY.md 等）。usbipd を使わず Windows
        # ネイティブ adb.exe を WSL から呼ぶ構成である旨を明文化する。
        result = ensure_adb_win_device(serial=serial)
        if result != 0:
            return result

    bundle_root, files = loaded
    for entry in files:
        source = resolve_artifact_src(bundle_root, entry["src"])
        if source is None:
            return 1

        target_dest = target_dest_path(entry["dest"], dest)
        result = provider.push_file(target, source, target_dest)
        if result != 0:
            return result

        mode = entry.get("mode")
        if isinstance(mode, str):
            proc = provider.run_remote(target, f"chmod {mode} {target_dest}", check=False)
            if proc.returncode != 0:
                return proc.returncode

    return 0


def ensure_adb_device(*, serial: str | None) -> int:
    result = subprocess.run(
        ["adb", "devices"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr.strip() or "gar target deploy: adb devices failed", file=sys.stderr)
        return result.returncode
    if adb_device_available(result.stdout, serial=serial):
        return 0

    print("gar target deploy: adb device not found; trying `gar usb attach`", file=sys.stderr)
    attach_result = run_usb_command("attach")
    if attach_result != 0:
        return attach_result

    result = subprocess.run(
        ["adb", "devices"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr.strip() or "gar target deploy: adb devices failed after usb attach", file=sys.stderr)
        return result.returncode
    if adb_device_available(result.stdout, serial=serial):
        return 0

    target = f" serial {serial}" if serial else ""
    print(f"gar target deploy: adb device{target} is still not visible after usb attach", file=sys.stderr)
    return 1


def ensure_adb_win_device(*, serial: str | None) -> int:
    """Windows ネイティブ adb.exe で device の存在を確認する（usbipd 不要）。"""
    from scripts.gar_lib.environments.registry.target_access.adb_win import _resolve_adb_exe

    exe = _resolve_adb_exe()
    if exe is None:
        print(
            "gar target deploy: adb.exe が見つかりません。`gar setup` で実機環境を選び "
            "adb.exe を導入してください。",
            file=sys.stderr,
        )
        return 1

    result = subprocess.run(
        [exe, "devices"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr.strip() or "gar target deploy: adb.exe devices failed", file=sys.stderr)
        return result.returncode
    if adb_device_available(result.stdout, serial=serial):
        return 0

    target = f" serial {serial}" if serial else ""
    print(
        f"gar target deploy: adb device{target} が見つかりません。"
        "USB-C 実機が Windows に接続され、認識されているか確認してください。",
        file=sys.stderr,
    )
    return 1


def adb_device_available(output: str, *, serial: str | None) -> bool:
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith("list of devices"):
            continue
        columns = line.split()
        if len(columns) < 2:
            continue
        device_serial, state = columns[0], columns[1]
        if state != "device":
            continue
        if serial is None or device_serial == serial:
            return True
    return False


def deploy_target_artifacts_ssh(root: Path, *, host: str, dest: str) -> int:
    loaded = load_deploy_files(root, "app")
    if loaded is None:
        return 1

    bundle_root, files = loaded
    provider = _get_provider("target_access")
    for entry in files:
        source = resolve_artifact_src(bundle_root, entry["src"])
        if source is None:
            return 1

        target_dest = target_dest_path(entry["dest"], dest)
        result = provider.push_file(host, source, target_dest)
        if result != 0:
            return result

        mode = entry.get("mode")
        if isinstance(mode, str):
            proc = provider.run_remote(host, f"chmod {mode} {target_dest}", check=False)
            if proc.returncode != 0:
                return proc.returncode

    return 0
