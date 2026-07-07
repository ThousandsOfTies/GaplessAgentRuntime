"""ESP32/M5Stack firmware artifact discovery, validation, and build helpers."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from scripts.gar_lib.artifacts.manifest import gh_env, select_codespace
from scripts.gar_lib.config import PROJECT_ROOT, load_config

DEFAULT_ESP32_ARTIFACT_ROOT = (
    PROJECT_ROOT.parent / "gar-vibe-ui" / "vibe-remote" / "m5stickc-client" / "artifacts"
)
DEFAULT_ESP32_CODESPACE_PROJECT_ROOT = (
    "/workspaces/gar-build-env/repos/apps/gar-vibe-ui/vibe-remote/m5stickc-client"
)
DEFAULT_ESP32_LOCAL_PROJECT_ROOT = DEFAULT_ESP32_ARTIFACT_ROOT.parent
DEFAULT_ESP32_PIO_ENV = "m5stickc-plus2-vibe-min"
FLASH_LAYOUT = (
    ("0x1000", "bootloader.bin"),
    ("0x8000", "partitions.bin"),
    ("0xE000", "boot_app0.bin"),
    ("0x10000", "firmware.bin"),
)


def find_latest_esp32_artifact(root: Path = DEFAULT_ESP32_ARTIFACT_ROOT) -> Path | None:
    if not root.exists():
        return None
    candidates = [
        path
        for path in root.iterdir()
        if path.is_dir() and (path / "firmware.bin").is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.name))


def resolve_esp32_artifact_dir(artifact_dir: str | None) -> Path | None:
    if artifact_dir:
        return Path(artifact_dir).expanduser().resolve()
    latest = find_latest_esp32_artifact()
    return latest.resolve() if latest else None


def parse_esp32_build_artifact_path(output: str) -> str | None:
    for line in output.splitlines():
        match = re.match(r"Artifact:\s*(\S+)\s*$", line.strip())
        if match:
            return match.group(1)
    return None


def run_streaming_command(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | str | None = None,
) -> tuple[int, str]:
    """Run a command while streaming output and keeping a copy for parsing."""
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        cwd=cwd,
        bufsize=1,
    )
    output_parts: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="")
        output_parts.append(line)
    return process.wait(), "".join(output_parts)


def _safe_extract_tar(tar_path: Path, dest: Path) -> None:
    dest_resolved = dest.resolve()
    with tarfile.open(tar_path, "r:gz") as archive:
        for member in archive.getmembers():
            target = (dest / member.name).resolve()
            if target != dest_resolved and dest_resolved not in target.parents:
                raise ValueError(f"tar member escapes destination: {member.name}")
        archive.extractall(dest)


def fetch_esp32_codespace_artifact(
    remote_artifact_dir: str,
    *,
    codespace: str,
    local_artifact_root: Path = DEFAULT_ESP32_ARTIFACT_ROOT,
) -> Path | None:
    remote_artifact = remote_artifact_dir.rstrip("/")
    remote_parent = str(Path(remote_artifact).parent)
    artifact_name = Path(remote_artifact).name
    local_artifact_root.mkdir(parents=True, exist_ok=True)
    local_artifact_dir = local_artifact_root / artifact_name

    command = (
        f"tar -czf - -C {shlex.quote(remote_parent)} {shlex.quote(artifact_name)}"
    )
    with tempfile.NamedTemporaryFile(prefix="gar-esp32-artifact-", suffix=".tgz", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        result = subprocess.run(
            ["gh", "codespace", "ssh", "-c", codespace, "--", command],
            check=False,
            stdout=tmp,
            stderr=subprocess.PIPE,
            text=False,
            env=gh_env(),
        )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace").strip()
        print(f"gar target build-esp32: failed to fetch {remote_artifact_dir}", file=sys.stderr)
        if stderr:
            print(stderr, file=sys.stderr)
        tmp_path.unlink(missing_ok=True)
        return None

    if local_artifact_dir.exists():
        import shutil

        shutil.rmtree(local_artifact_dir)
    try:
        _safe_extract_tar(tmp_path, local_artifact_root)
    except (tarfile.TarError, OSError, ValueError) as exc:
        print(f"gar target build-esp32: failed to extract artifact: {exc}", file=sys.stderr)
        tmp_path.unlink(missing_ok=True)
        return None
    finally:
        tmp_path.unlink(missing_ok=True)

    return local_artifact_dir.resolve()


def run_esp32_build_command(
    *,
    codespace: str | None = None,
    remote_project_root: str = DEFAULT_ESP32_CODESPACE_PROJECT_ROOT,
    pio_env: str = DEFAULT_ESP32_PIO_ENV,
    local_artifact_root: str | None = None,
    flash: bool = False,
    port: str | None = None,
    baud: int = 921600,
    chip: str = "esp32",
    verify: bool = True,
    install_esptool: bool = True,
) -> int:
    config = load_config()
    development_provider = config.get("selected_providers", {}).get("codespace")

    if development_provider == "local":
        return run_esp32_build_local(
            pio_env=pio_env,
            local_artifact_root=local_artifact_root,
            flash=flash,
            port=port,
            baud=baud,
            chip=chip,
            verify=verify,
            install_esptool=install_esptool,
        )

    if development_provider not in (None, "github_codespaces"):
        print(
            "gar target build: 現在の setup では対応する build が見つかりません。\n"
            f"  development: {development_provider}\n"
            "  Run `gar setup` and choose Local or GitHub Codespaces.",
            file=sys.stderr,
        )
        return 1

    selected_codespace = select_codespace(codespace)
    if not selected_codespace:
        print("gar target build-esp32: pass --codespace NAME or set GAR_CODESPACE_NAME", file=sys.stderr)
        return 1

    remote_project = remote_project_root.rstrip("/")
    remote_command = (
        f"cd {shlex.quote(remote_project)} && "
        'PATH="$HOME/.venvs/platformio/bin:$PATH" '
        f"./scripts/vm_build_and_package.sh {shlex.quote(pio_env)}"
    )
    print(f"Codespace: {selected_codespace}")
    print(f"Remote project: {remote_project}")
    print(f"PIO env: {pio_env}")
    returncode, build_output = run_streaming_command(
        ["gh", "codespace", "ssh", "-c", selected_codespace, "--", remote_command],
        env=gh_env(),
    )
    if returncode != 0:
        return returncode

    remote_artifact_dir = parse_esp32_build_artifact_path(build_output)
    if not remote_artifact_dir:
        print("gar target build-esp32: build output did not include an Artifact path", file=sys.stderr)
        return 1

    root = Path(local_artifact_root).expanduser() if local_artifact_root else DEFAULT_ESP32_ARTIFACT_ROOT
    local_artifact_dir = fetch_esp32_codespace_artifact(
        remote_artifact_dir,
        codespace=selected_codespace,
        local_artifact_root=root,
    )
    if local_artifact_dir is None:
        return 1
    print(f"Artifact: {local_artifact_dir}")

    if flash:
        from scripts.gar_lib.environments.registry.target.esp32_esptool import run_esp32_flash_command

        return run_esp32_flash_command(
            artifact_dir=str(local_artifact_dir),
            port=port,
            baud=baud,
            chip=chip,
            verify=verify,
            install_esptool=install_esptool,
        )
    return 0


def run_esp32_build_local(
    *,
    pio_env: str = DEFAULT_ESP32_PIO_ENV,
    local_artifact_root: str | None = None,
    flash: bool = False,
    port: str | None = None,
    baud: int = 921600,
    chip: str = "esp32",
    verify: bool = True,
    install_esptool: bool = True,
) -> int:
    project_root = DEFAULT_ESP32_LOCAL_PROJECT_ROOT
    build_script = project_root / "scripts" / "vm_build_and_package.sh"
    if not build_script.is_file():
        print(f"gar target build: build script not found: {build_script}", file=sys.stderr)
        return 1

    env = os.environ.copy()
    platformio_bin = Path.home() / ".venvs" / "platformio" / "bin"
    env["PATH"] = f"{platformio_bin}:{env.get('PATH', '')}"

    print(f"Local project: {project_root}")
    print(f"PIO env: {pio_env}")
    returncode, build_output = run_streaming_command(
        ["./scripts/vm_build_and_package.sh", pio_env],
        env=env,
        cwd=project_root,
    )
    if returncode != 0:
        return returncode

    artifact_dir = parse_esp32_build_artifact_path(build_output)
    if not artifact_dir:
        print("gar target build: build output did not include an Artifact path", file=sys.stderr)
        return 1
    local_artifact_dir = Path(artifact_dir).expanduser().resolve()

    if local_artifact_root:
        root = Path(local_artifact_root).expanduser().resolve()
        if root != local_artifact_dir.parent:
            import shutil

            root.mkdir(parents=True, exist_ok=True)
            dest = root / local_artifact_dir.name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(local_artifact_dir, dest)
            local_artifact_dir = dest

    print(f"Artifact: {local_artifact_dir}")

    if flash:
        from scripts.gar_lib.environments.registry.target.esp32_esptool import run_esp32_flash_command

        return run_esp32_flash_command(
            artifact_dir=str(local_artifact_dir),
            port=port,
            baud=baud,
            chip=chip,
            verify=verify,
            install_esptool=install_esptool,
        )
    return 0
