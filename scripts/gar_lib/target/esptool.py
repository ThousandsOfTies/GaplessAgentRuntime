"""ESP32 artifact flashing through esptool."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import stat
import subprocess
import sys
import venv
from pathlib import Path

from scripts.gar_lib.config import load_config, saved_esp32_serial_port
from scripts.gar_lib.targets.esp32 import (
    DEFAULT_ESP32_ARTIFACT_ROOT,
    FLASH_LAYOUT,
    resolve_esp32_artifact_dir,
)

ESPTOOL_VENV = Path.home() / ".local" / "share" / "gar" / "esptool-venv"


def normalize_esp32_serial_port(port: str | None) -> str | None:
    """Map Windows COM names to WSL ttyS names when running from Linux."""

    value = port or os.environ.get("GAR_ESP32_PORT") or saved_esp32_serial_port(load_config())
    if not value:
        return None
    match = re.fullmatch(r"COM(\d+)", value, flags=re.IGNORECASE)
    if os.name == "posix" and match:
        return f"/dev/ttyS{match.group(1)}"
    return value


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
            "gar target flash-esp32: ESP32 serial port is not configured.\n"
            "Run: gar setup\n"
            "or:  gar target flash-esp32 --port COM3",
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
