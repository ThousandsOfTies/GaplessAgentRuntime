"""ESP32/M5Stack firmware artifact flashing via esptool."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import shlex
import stat
import subprocess
import sys
import tarfile
import tempfile
import venv
from pathlib import Path

from scripts.gar_lib._config import PROJECT_ROOT
from scripts.gar_lib._deploy import gh_env, select_codespace

DEFAULT_ESP32_ARTIFACT_ROOT = (
    PROJECT_ROOT.parent / "gar-vibe-ui" / "vibe-remote" / "m5stickc-client" / "artifacts"
)
DEFAULT_ESP32_CODESPACE_PROJECT_ROOT = (
    "/workspaces/gar-build-env/repos/apps/gar-vibe-ui/vibe-remote/m5stickc-client"
)
DEFAULT_ESP32_PIO_ENV = "m5stickc-plus2-vibe-min"
ESPTOOL_VENV = Path.home() / ".local" / "share" / "gar" / "esptool-venv"
FLASH_LAYOUT = (
    ("0x1000", "bootloader.bin"),
    ("0x8000", "partitions.bin"),
    ("0xE000", "boot_app0.bin"),
    ("0x10000", "firmware.bin"),
)


def normalize_esp32_serial_port(port: str | None) -> str | None:
    """Map Windows COM names to WSL ttyS names when running from Linux."""

    value = port or os.environ.get("GAR_ESP32_PORT")
    if not value:
        return None
    match = re.fullmatch(r"COM(\d+)", value, flags=re.IGNORECASE)
    if os.name == "posix" and match:
        return f"/dev/ttyS{match.group(1)}"
    return value


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
    result = subprocess.run(
        ["gh", "codespace", "ssh", "-c", selected_codespace, "--", remote_command],
        check=False,
        capture_output=True,
        text=True,
        env=gh_env(),
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr.strip(), file=sys.stderr)
        return result.returncode

    remote_artifact_dir = parse_esp32_build_artifact_path(result.stdout)
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
        return run_esp32_flash_command(
            artifact_dir=str(local_artifact_dir),
            port=port,
            baud=baud,
            chip=chip,
            verify=verify,
            install_esptool=install_esptool,
        )
    return 0


def validate_esp32_artifact(artifact_dir: Path) -> bool:
    if not artifact_dir.is_dir():
        print(f"gar target flash-esp32: artifact dir not found: {artifact_dir}", file=sys.stderr)
        return False
    missing = [name for _, name in FLASH_LAYOUT if not (artifact_dir / name).is_file()]
    if missing:
        print(
            "gar target flash-esp32: missing artifact file(s): " + ", ".join(missing),
            file=sys.stderr,
        )
        return False
    return True


def esp32_serial_port_access_error(port: str) -> str | None:
    if os.name != "posix" or not port.startswith("/dev/"):
        return None
    path = Path(port)
    if not path.exists():
        return f"serial port not found: {port}"
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        return f"cannot stat serial port {port}: {exc}"
    if not stat.S_ISCHR(mode):
        return f"serial port is not a character device: {port}"
    if os.access(path, os.R_OK | os.W_OK):
        return None

    hint = ""
    try:
        import grp

        group_name = grp.getgrgid(path.stat().st_gid).gr_name
    except (ImportError, KeyError, OSError):
        group_name = ""
    if group_name:
        hint = (
            f"\nHint: {port} belongs to group '{group_name}'. "
            f"Run: sudo usermod -aG {group_name} $USER"
            "\nThen restart WSL or log out/in so the new group is applied."
        )
    return f"serial port is not readable/writable by current user: {port}{hint}"


def esp32_serial_failure_hint(port: str) -> str | None:
    if os.name != "posix":
        return None
    if re.fullmatch(r"/dev/ttyS\d+", port):
        return (
            "Hint: esptool could open the WSL COM port but flashing still failed. "
            "Close any Windows serial monitor using the COM port. If it still reports "
            "'Input/output error', attach the USB serial device to WSL with usbipd and "
            "retry using /dev/ttyUSB0 instead of COM3."
        )
    return None


def verify_esp32_artifact_checksums(artifact_dir: Path) -> bool:
    sums_path = artifact_dir / "SHA256SUMS"
    if not sums_path.exists():
        print("SHA256SUMS not found; skipping checksum verification.")
        return True

    ok = True
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            print(f"invalid SHA256SUMS line: {line}", file=sys.stderr)
            ok = False
            continue
        expected, filename = parts
        filename = filename.lstrip("*")
        target = artifact_dir / filename
        if not target.is_file():
            print(f"{filename}: missing", file=sys.stderr)
            ok = False
            continue
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual.lower() != expected.lower():
            print(f"{filename}: FAILED", file=sys.stderr)
            ok = False
        else:
            print(f"{filename}: OK")
    return ok


def _venv_python(path: Path) -> Path:
    if os.name == "nt":
        return path / "Scripts" / "python.exe"
    return path / "bin" / "python"


def ensure_esptool_python(*, install: bool = True) -> Path | None:
    if importlib.util.find_spec("esptool") is not None:
        return Path(sys.executable)

    python = _venv_python(ESPTOOL_VENV)
    if python.exists():
        return python
    if not install:
        return None

    print(f"Installing esptool into GAR-managed venv: {ESPTOOL_VENV}")
    ESPTOOL_VENV.parent.mkdir(parents=True, exist_ok=True)
    venv.EnvBuilder(with_pip=True).create(ESPTOOL_VENV)
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "--upgrade", "pip", "esptool"],
        check=False,
    )
    if result.returncode != 0:
        return None
    return python


def run_esp32_flash_command(
    *,
    artifact_dir: str | None = None,
    port: str | None = None,
    baud: int = 921600,
    chip: str = "esp32",
    verify: bool = True,
    install_esptool: bool = True,
) -> int:
    resolved_artifact_dir = resolve_esp32_artifact_dir(artifact_dir)
    if resolved_artifact_dir is None:
        print(
            f"gar target flash-esp32: no artifact found under {DEFAULT_ESP32_ARTIFACT_ROOT}",
            file=sys.stderr,
        )
        return 1
    resolved_port = normalize_esp32_serial_port(port)
    if not resolved_port:
        print(
            "gar target flash-esp32: --port is required "
            "(example: --port COM3 or --port /dev/ttyS3)",
            file=sys.stderr,
        )
        return 1
    if not validate_esp32_artifact(resolved_artifact_dir):
        return 1
    port_error = esp32_serial_port_access_error(resolved_port)
    if port_error:
        print(f"gar target flash-esp32: {port_error}", file=sys.stderr)
        return 1
    if verify and not verify_esp32_artifact_checksums(resolved_artifact_dir):
        return 1

    esptool_python = ensure_esptool_python(install=install_esptool)
    if esptool_python is None:
        print(
            "gar target flash-esp32: esptool not found. "
            "Re-run without --no-install-esptool or install esptool manually.",
            file=sys.stderr,
        )
        return 1

    args = [
        str(esptool_python),
        "-m",
        "esptool",
        "--chip",
        chip,
        "--port",
        resolved_port,
        "--baud",
        str(baud),
        "--before",
        "default-reset",
        "--after",
        "hard-reset",
        "write-flash",
        "-z",
    ]
    for offset, filename in FLASH_LAYOUT:
        args.extend([offset, str(resolved_artifact_dir / filename)])

    print(f"Artifact: {resolved_artifact_dir}")
    print(f"Port: {resolved_port}")
    result = subprocess.run(args, check=False)
    if result.returncode == 0:
        print("Flash complete.")
    else:
        hint = esp32_serial_failure_hint(resolved_port)
        if hint:
            print(hint, file=sys.stderr)
    return result.returncode
