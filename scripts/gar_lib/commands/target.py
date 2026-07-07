"""`gar target build/build-esp32/flash-esp32/deploy`: target_access provider dispatch.

The actual build/flash/deploy work lives on ``DevEnvironment`` subclasses
(``.build()``/``.flash()``/``.deploy()``, see :mod:`scripts.gar_lib.environments.base`
and the ``environments/registry/target_access/*`` providers). This module:

- resolves the selected ``target_access`` provider and adapts CLI-facing call
  signatures (``run_target_build_command``/``run_target_flash_command``),
  catching ``NotImplementedError`` to print ``gar setup`` guidance
- provides adb device-readiness helpers and the plain file-push deploy used by
  the ``adb_usb``/``adb_win``/``ssh_scp`` providers' ``deploy()`` overrides
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.gar_lib.artifacts.manifest import (
    get_provider,
    load_deploy_files,
    resolve_artifact_src,
    target_dest_path,
)
from scripts.gar_lib.commands.usb import run_usb_command


def run_target_build_command(
    *,
    codespace: str | None,
    remote_project_root: str,
    pio_env: str,
    local_artifact_root: str | None,
    flash: bool,
    port: str | None,
    baud: int,
    chip: str,
    verify: bool,
    install_esptool: bool,
) -> int:
    provider = get_provider("target_access")
    try:
        return provider.build(
            codespace=codespace,
            remote_project_root=remote_project_root,
            pio_env=pio_env,
            local_artifact_root=local_artifact_root,
            flash=flash,
            port=port,
            baud=baud,
            chip=chip,
            verify=verify,
            install_esptool=install_esptool,
        )
    except NotImplementedError:
        print(
            "gar target build: 現在の setup では対応する build が見つかりません。\n"
            f"  target_access: {provider.display_name}\n"
            "  Run `gar setup` and choose ESP32 esptool.",
            file=sys.stderr,
        )
        return 1


def run_target_flash_command(
    *,
    artifact_dir: str | None,
    port: str | None,
    baud: int,
    chip: str,
    verify: bool,
    install_esptool: bool,
) -> int:
    provider = get_provider("target_access")
    try:
        return provider.flash(
            artifact_dir=artifact_dir,
            port=port,
            baud=baud,
            chip=chip,
            verify=verify,
            install_esptool=install_esptool,
        )
    except NotImplementedError:
        print(
            "gar target flash-esp32: 現在の setup では対応する flash が見つかりません。\n"
            f"  target_access: {provider.display_name}\n"
            "  Run `gar setup` and choose ESP32 esptool.",
            file=sys.stderr,
        )
        return 1


def run_target_deploy_command(
    artifacts_dir: str | None,
    *,
    serial: str | None = None,
    port: str | None = None,
    host: str | None = None,
    dest: str = "/home/user",
    codespace: str | None = None,
    remote_root: str | None = None,
) -> int:
    del codespace, remote_root
    provider = get_provider("target_access")
    try:
        return provider.deploy(artifacts_dir, serial=serial, port=port, host=host, dest=dest)
    except NotImplementedError:
        print(
            "gar target deploy: 現在の setup では対応する deploy が見つかりません。\n"
            f"  target_access: {provider.display_name}\n"
            "  Run `gar setup` and choose a target access provider.",
            file=sys.stderr,
        )
        return 1


def selected_target_access_provider_id(config: dict) -> str | None:
    selected = config.get("selected_providers")
    if isinstance(selected, dict):
        value = selected.get("target_access")
        if isinstance(value, str) and value:
            return value
    return None


def deploy_target_artifacts(root: Path, *, serial: str | None, dest: str) -> int:
    loaded = load_deploy_files(root, "app")
    if loaded is None:
        return 1

    provider = get_provider("target_access")
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
    provider = get_provider("target_access")
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
