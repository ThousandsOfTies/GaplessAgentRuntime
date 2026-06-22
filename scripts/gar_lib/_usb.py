"""`gar usb` subcommand: USB-C passthrough to WSL2 via usbipd-win.

WSL2 から Windows interop で ``usbipd.exe`` を呼び出し、USB-C 実機（ADB）を
WSL2 に attach する。busid は自動検出し、一度確定したものは ``.gar/config.json``
に記憶するので、2 回目以降は ``gar usb attach`` だけで済む。

前提:
- Windows 側に usbipd-win が install 済み。
- 対象デバイスは一度だけ管理者権限で ``usbipd bind`` 済み（再起動後も保持）。
  未 share の場合は本コマンドがその旨を案内する。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

from scripts.gar_lib._config import (
    load_config,
    save_config,
    saved_usb_busid,
    set_saved_usb_busid,
)

# ADB 実機らしさを判定するためのキーワード（description 内、大文字小文字無視）。
ANDROID_HINTS = ("adb", "android")
# 既知ベンダの USB VID（先頭 4 桁）。Google / よくある Android ベンダ。
ANDROID_VIDS = ("18d1",)


@dataclass(frozen=True)
class UsbDevice:
    busid: str
    vid_pid: str
    description: str
    state: str

    @property
    def is_shared(self) -> bool:
        state = self.state.strip().lower()
        if state.startswith("not shared"):
            return False
        return "shared" in state or "attached" in state

    @property
    def is_attached(self) -> bool:
        return "attached" in self.state.lower()

    @property
    def looks_like_android(self) -> bool:
        description = self.description.lower()
        if any(hint in description for hint in ANDROID_HINTS):
            return True
        vid = self.vid_pid.split(":", 1)[0].lower()
        return vid in ANDROID_VIDS


def _usbipd_executable() -> str | None:
    return shutil.which("usbipd.exe") or shutil.which("usbipd")


def _run_usbipd(args: list[str]) -> subprocess.CompletedProcess[str]:
    executable = _usbipd_executable()
    if executable is None:
        raise FileNotFoundError("usbipd")
    return subprocess.run(
        [executable, *args],
        check=False,
        capture_output=True,
        text=True,
    )


def parse_usbipd_list(output: str) -> list[UsbDevice]:
    """``usbipd list`` の Connected セクションを行ごとに解析する。"""
    devices: list[UsbDevice] = []
    in_connected = False
    # BUSID  VID:PID  DEVICE...  STATE  という列。BUSID は数字-数字 で始まる。
    row_pattern = re.compile(
        r"^(?P<busid>\d+-\d+)\s+"
        r"(?P<vidpid>[0-9a-fA-F]{4}:[0-9a-fA-F]{4})\s+"
        r"(?P<rest>.+?)\s*$"
    )
    known_states = ("not shared", "shared (forced)", "shared", "attached")

    for raw_line in output.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.lower().startswith("connected:"):
            in_connected = True
            continue
        if stripped.lower().startswith("persisted:"):
            in_connected = False
            continue
        if not in_connected or not stripped:
            continue
        if stripped.lower().startswith("busid"):
            continue

        match = row_pattern.match(line)
        if not match:
            continue

        rest = match.group("rest")
        state = ""
        lowered = rest.lower()
        for candidate in known_states:
            index = lowered.rfind(candidate)
            if index != -1:
                state = rest[index:].strip()
                rest = rest[:index].strip()
                break

        devices.append(
            UsbDevice(
                busid=match.group("busid"),
                vid_pid=match.group("vidpid"),
                description=rest,
                state=state,
            )
        )
    return devices


def list_usb_devices() -> list[UsbDevice]:
    result = _run_usbipd(["list"])
    if result.returncode != 0:
        print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
        return []
    return parse_usbipd_list(result.stdout)


def _format_device(device: UsbDevice) -> str:
    return f"{device.busid:>6}  {device.vid_pid}  {device.description}  [{device.state}]"


def _resolve_target(
    devices: list[UsbDevice],
    *,
    busid: str | None,
    match: str | None = None,
    config: dict,
) -> UsbDevice | None:
    """attach 対象を決定する。明示 busid > match > 保存済み busid > Android 自動検出。"""
    if busid:
        for device in devices:
            if device.busid == busid:
                return device
        print(f"gar usb: busid {busid} のデバイスが見つかりません。", file=sys.stderr)
        return None

    if match:
        lowered_match = match.lower()
        candidates = [
            device
            for device in devices
            if lowered_match in device.description.lower()
            or lowered_match in device.vid_pid.lower()
            or lowered_match == device.busid.lower()
        ]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            print(f"gar usb: match {match!r} の候補が複数あります。--busid で指定してください:", file=sys.stderr)
            for device in candidates:
                print(f"  {_format_device(device)}", file=sys.stderr)
            return None
        print(f"gar usb: match {match!r} のデバイスが見つかりません。", file=sys.stderr)
        return None

    remembered = saved_usb_busid(config)
    if remembered:
        for device in devices:
            if device.busid == remembered:
                return device

    candidates = [device for device in devices if device.looks_like_android]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        print("gar usb: ADB 実機の候補が複数あります。--busid で指定してください:", file=sys.stderr)
        for device in candidates:
            print(f"  {_format_device(device)}", file=sys.stderr)
        return None

    print(
        "gar usb: ADB 実機を自動検出できませんでした。`gar usb list` で busid を確認し "
        "`gar usb attach --busid <busid>` を実行してください。",
        file=sys.stderr,
    )
    return None


def _print_bind_hint(busid: str) -> None:
    print(
        "gar usb: このデバイスはまだ share されていません。\n"
        "  USB 機器を WSL に接続できるようにするため、Host OS の usbipd bind が必要です。\n"
        "  まず WSL から次を試してください（Host OS 側の管理者権限が必要な場合があります）:\n"
        f"    gar usb bind --busid {busid}\n"
        "  管理者権限不足でエラーになる場合は、Host OS 上でコマンドプロンプトまたは "
        "PowerShell を管理者権限で開いて、次を実行してください:\n"
        f"    usbipd bind --busid {busid}",
        file=sys.stderr,
    )


def _print_bind_admin_hint(busid: str) -> None:
    print(
        "gar usb: USB 機器を WSL に接続するために Host OS の usbipd bind を実行しましたが、"
        "管理者権限不足でエラーになりました。\n"
        "  Host OS 上でコマンドプロンプトまたは PowerShell を管理者権限で開いて、"
        "次を実行してください:\n"
        f"    usbipd bind --busid {busid}\n"
        "  bind が成功した後は、WSL 側で次を実行してください:\n"
        f"    gar usb attach --busid {busid}",
        file=sys.stderr,
    )


def _device_to_dict(device: UsbDevice) -> dict:
    return {
        "busid": device.busid,
        "vid_pid": device.vid_pid,
        "description": device.description,
        "state": device.state,
        "is_shared": device.is_shared,
        "is_attached": device.is_attached,
        "looks_like_android": device.looks_like_android,
    }


def run_usb_command(
    command: str,
    *,
    busid: str | None = None,
    match: str | None = None,
    remember: bool = True,
    json_output: bool = False,
) -> int:
    if _usbipd_executable() is None:
        print(
            "gar usb: usbipd.exe が見つかりません。Windows 側に usbipd-win を install してください。\n"
            "  winget install --interactive --exact dorssel.usbipd-win",
            file=sys.stderr,
        )
        return 1

    try:
        devices = list_usb_devices()
    except FileNotFoundError:
        print("gar usb: usbipd.exe の実行に失敗しました。", file=sys.stderr)
        return 1

    if command == "list":
        if json_output:
            print(
                json.dumps(
                    {
                        "command": "usb list",
                        "devices": [_device_to_dict(d) for d in devices],
                        "count": len(devices),
                        "ok": True,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if not devices:
            print("接続中の USB デバイスがありません。")
            return 0
        for device in devices:
            print(_format_device(device))
        return 0

    config = load_config()

    if command == "status":
        target = _resolve_target(devices, busid=busid, match=match, config=config)
        if target is None:
            if json_output:
                print(
                    json.dumps(
                        {
                            "command": "usb status",
                            "ok": False,
                            "device": None,
                            "error": "target device not found",
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return 1
        if json_output:
            print(
                json.dumps(
                    {
                        "command": "usb status",
                        "ok": True,
                        "device": _device_to_dict(target),
                        "attached": target.is_attached,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0 if target.is_attached else 1
        print(_format_device(target))
        return 0 if target.is_attached else 1

    if command == "bind":
        target = _resolve_target(devices, busid=busid, match=match, config=config)
        if target is None:
            return 1
        if target.is_shared:
            print(f"gar usb: 既に share/attach 済みです: {_format_device(target)}")
            if remember:
                _remember(config, target.busid)
            return 0
        result = _run_usbipd(["bind", "--busid", target.busid])
        if result.returncode != 0:
            print(result.stderr.strip() or "bind に失敗しました。", file=sys.stderr)
            _print_bind_admin_hint(target.busid)
            return result.returncode
        print(f"gar usb: share しました: {target.busid} ({target.description})")
        if remember:
            _remember(config, target.busid)
        return 0

    if command == "attach":
        target = _resolve_target(devices, busid=busid, match=match, config=config)
        if target is None:
            return 1

        if target.is_attached:
            print(f"gar usb: 既に attach 済みです: {_format_device(target)}")
            if remember:
                _remember(config, target.busid)
            return 0

        if not target.is_shared:
            _print_bind_hint(target.busid)
            return 1

        result = _run_usbipd(["attach", "--wsl", "--busid", target.busid])
        if result.returncode != 0:
            stderr = result.stderr.strip()
            print(stderr or "attach に失敗しました。", file=sys.stderr)
            if "administrator" in stderr.lower() or "bind" in stderr.lower():
                _print_bind_hint(target.busid)
            return result.returncode

        print(f"gar usb: attach しました: {target.busid} ({target.description})")
        if remember:
            _remember(config, target.busid)
        return 0

    if command == "detach":
        target = _resolve_target(devices, busid=busid, match=match, config=config)
        if target is None:
            return 1
        result = _run_usbipd(["detach", "--busid", target.busid])
        if result.returncode != 0:
            print(result.stderr.strip() or "detach に失敗しました。", file=sys.stderr)
            return result.returncode
        print(f"gar usb: detach しました: {target.busid}")
        return 0

    print(f"unknown usb command: {command}", file=sys.stderr)
    return 1


def _remember(config: dict, busid: str) -> None:
    if saved_usb_busid(config) == busid:
        return
    set_saved_usb_busid(config, busid)
    save_config(config)
