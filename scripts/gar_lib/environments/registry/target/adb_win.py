"""Windows-native ADB device provider (called from WSL via interop).

方式2: USB-C 実機は Windows がネイティブ認識し、WSL からは Windows の
``adb.exe`` を直接呼ぶ。``usbipd-win`` による attach/bind は不要。

ローカル側（WSL）のファイルパスのみ ``wslpath -w`` で Windows 形式へ変換して
``adb.exe`` に渡す。device 側のパス（dest）は Linux のままで変換しない。

``adb.exe`` の場所は ``gar setup`` 時に確定し、``.gar/config.json`` の
``adb.exe_path`` に保存する。実行時は 保存パス > PATH 上の ``adb.exe`` の順で解決する。
"""

from __future__ import annotations

import shutil
import subprocess

from scripts.gar_lib.config import (
    load_config,
    save_config,
    saved_adb_exe,
    set_saved_adb_exe,
)
from scripts.gar_lib.environments.base import EnvironmentSetupOption

# winget の Android Platform Tools パッケージ ID。
WINGET_PACKAGE_ID = "Google.PlatformTools"


class AdbWinEnvironment(EnvironmentSetupOption):
    provider_id = "adb_win"
    display_name = "ADB (Windows native)"
    description = (
        "Windows ネイティブの adb.exe を WSL から呼び出して USB-C 実機へ接続します"
        "（usbipd 不要）"
    )
    display_order = 15
    required_commands = ("adb.exe",)

    @classmethod
    def install_hint(cls, missing: list[str]) -> str:
        return (
            "Windows 側に Android Platform Tools (adb.exe) をインストールしてください。\n"
            "  winget install --exact --id Google.PlatformTools\n"
            "インストール後、adb.exe が Windows の PATH に含まれるようにしてください。"
        )

    @classmethod
    def install_dependencies(cls, missing: list[str]) -> int:
        winget = shutil.which("winget.exe")
        if winget is None:
            print(cls.install_hint(missing))
            return 1

        print("Windows へ Android Platform Tools を winget でインストールします。")
        result = cls.run_install_command(
            [
                winget,
                "install",
                "--exact",
                "--id",
                WINGET_PACKAGE_ID,
                "--accept-source-agreements",
                "--accept-package-agreements",
            ]
        )
        if result != 0:
            print(cls.install_hint(missing))
            return result

        # winget 直後は同一プロセスの PATH が未更新で which が拾えないことがある。
        # 確定できたパスは config に保存して以降 PATH 非依存にする。
        cls.remember_adb_exe()
        return 0

    # TODO(外形ゆえの暫定): `gar setup` で adb_win を選んだ際、検出成功時にも
    # remember_adb_exe() を呼んで確定パスを保存する導線が必要。現状は
    # install_dependencies 経由（winget インストール時）でのみ保存される。
    @classmethod
    def remember_adb_exe(cls) -> str | None:
        """adb.exe のパスを解決し、見つかれば config に保存して返す。"""
        exe = shutil.which("adb.exe")
        if exe is None:
            return None

        version = None
        proc = subprocess.run(
            [exe, "version"],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            version = proc.stdout.strip().splitlines()[0].strip()

        config = load_config()
        if saved_adb_exe(config) != exe:
            set_saved_adb_exe(config, exe, version=version)
            save_config(config)
        return exe
