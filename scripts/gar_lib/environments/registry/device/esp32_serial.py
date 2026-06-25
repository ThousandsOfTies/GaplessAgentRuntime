"""ESP32 Physical Device Serial Provider (Stub/Skeleton).

This file is a placeholder/stub to guide future implementation of the ESP32
physical device access driver.

# 目的と方針 (Purpose & Policy for Future Agents)
- **目的**: USB/シリアルケーブルで接続されたESP32等の実機に対して、ファームウェアの書き込みやREPLコマンドの実行を行う。
- **ツール**: MicroPython環境であれば `mpremote` や `ampy`、ESP-IDF(C/C++)環境であれば `esptool.py` などを利用してシリアル通信を行う。
- **アーキテクチャの相違点**:
  - `adb_usb` (Android/RaspberryPi等) では `adb shell` を使ってLinuxコマンドを実行し、`adb push` でファイルを転送していた。
  - `esp32_serial` では、ターゲットとなるシリアルポート (例: `/dev/ttyUSB0` や `COM3`) に対して直接コマンドやファイルを送り込む形になる。
- **今後の実装タスク**:
  1. `esptool` または `mpremote` (MicroPythonの場合) などの必要なコマンドのインストールチェック (`install_dependencies`) を実装する。
  2. `run_remote()` にて、シリアルポートを開いてMicroPython REPL上で直接Pythonコードを実行するか、`esptool` でのリセット/モニタ起動を実行する。
  3. `push_file()` にて、ESP32のフラッシュメモリ領域へバイナリ書き込み (`esptool.py write_flash`) を行うか、MicroPythonのファイルシステム (`mpremote fs cp`) にファイルをコピーする処理を実装する。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.gar_lib._config import PROJECT_ROOT
from scripts.gar_lib.environments.base import CommandStatus, DevEnvironment


def _unsupported() -> None:
    print(
        "gar: ESP32 USB Serial provider is not implemented yet.",
        file=sys.stderr,
    )


class Esp32SerialEnvironment(DevEnvironment):
    provider_id = "esp32_serial"
    display_name = "ESP32 USB Serial"
    description = "esptool で ESP32/M5Stack firmware を USBシリアル経由で実機へ書き込みます"
    display_order = 20

    required_commands = ("esptool",)

    @classmethod
    def dependency_status(cls) -> list[CommandStatus]:
        return [CommandStatus(name="esptool", path=_find_tool("esptool"))]

    @classmethod
    def install_hint(cls, missing: list[str]) -> str:
        commands = ", ".join(missing)
        return (
            f"不足: {commands}\n"
            "GAR の .venv に ESP32 書き込みツール esptool をインストールします。\n"
            "MicroPython REPL/ファイル転送も使う場合は mpremote も追加できます。\n"
            "手動で行う場合: .venv/bin/python -m pip install esptool"
        )

    @classmethod
    def install_dependencies(cls, missing: list[str]) -> int:
        if "esptool" not in missing:
            print(cls.install_hint(missing))
            return 1

        python = _install_python()
        if python is None:
            print(cls.install_hint(missing))
            return 1

        print("ESP32 firmware 書き込みツール esptool を GAR の .venv にインストールします。")
        result = cls.run_subprocess([str(python), "-m", "pip", "install", "esptool"])
        if result == 0:
            _refresh_tool_path()
        return result

    @classmethod
    def run_remote(cls, target: str, command: str, *, capture_output: bool = False, text: bool = True, check: bool = False):
        """シリアルポート経由でコマンドを実行する。

        target: シリアルポート (例: '/dev/ttyUSB0', 'COM3')
        command: 実行するMicroPythonコードや、esptoolへの引数など

        [実装例 (MicroPython `mpremote` の場合)]
        cmd = ["mpremote", "connect", target, "exec", command]
        return subprocess.run(cmd, ...)
        """
        _unsupported()
        result = subprocess.CompletedProcess(args=["esp32_serial", target, command], returncode=1)
        if check:
            raise subprocess.CalledProcessError(result.returncode, result.args)
        return result

    @classmethod
    def push_file(cls, target: str, src, dest) -> int:
        """ローカルのファイルをESP32へ転送、またはファームウェアをフラッシュする。

        target: シリアルポート (例: '/dev/ttyUSB0')
        src: ローカルのファイルパス
        dest: ESP32内の保存先 (MicroPythonの場合は '/flash/boot.py' など)

        [実装例 (MicroPython `mpremote` の場合)]
        cmd = ["mpremote", "connect", target, "fs", "cp", str(src), f":{dest}"]
        return subprocess.run(cmd).returncode
        """
        _unsupported()
        return 1

    @classmethod
    def pull_file(cls, target: str, src, dest) -> int:
        """ESP32からローカルへファイルをダウンロードする。"""
        _unsupported()
        return 1


def _find_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found

    for path in _tool_candidate_paths(name):
        if path.exists() and os.access(path, os.X_OK):
            return str(path)

    return None


def _tool_candidate_paths(name: str) -> list[Path]:
    return [
        PROJECT_ROOT / ".venv" / "bin" / name,
        Path.home() / ".local" / "bin" / name,
    ]


def _install_python() -> Path | None:
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return venv_python
    return Path(sys.executable) if sys.executable else None


def _refresh_tool_path() -> None:
    current_parts = os.environ.get("PATH", "").split(os.pathsep)
    extra_dirs = []
    for path in _tool_candidate_paths("esptool"):
        parent = str(path.parent)
        if path.exists() and parent not in current_parts:
            extra_dirs.append(parent)

    if extra_dirs:
        os.environ["PATH"] = os.pathsep.join([*extra_dirs, *current_parts])
