from __future__ import annotations

import platform
import shutil

from scripts.gar_lib.environments.base import EnvironmentSetupOption
from scripts.gar_lib.environments.install import print_user_terminal_handoff, sudo_block_reason


class AdbUsbEnvironment(EnvironmentSetupOption):
    provider_id = "adb_usb"
    display_name = "ADB USB-C"
    description = "adb コマンドで USB-C 接続の実機へ接続します"
    display_order = 10
    required_commands = ("adb",)

    @classmethod
    def install_hint(cls, missing: list[str]) -> str:
        commands = ", ".join(missing)
        return (
            f"不足: {commands}\n"
            "Android Platform Tools の adb をインストールしてください。"
        )

    @classmethod
    def install_dependencies(cls, missing: list[str]) -> int:
        if "adb" not in missing:
            print(cls.install_hint(missing))
            return 1

        if platform.system() != "Linux" or shutil.which("apt-get") is None:
            print(cls.install_hint(missing))
            return 1

        blocked = sudo_block_reason()
        if blocked:
            print_user_terminal_handoff(
                "adb のインストールには sudo が必要です。",
                [
                    "sudo apt-get update",
                    "sudo apt-get install -y adb",
                ],
                reason=blocked,
            )
            return 1

        print("adb を apt-get でインストールします。")
        print("sudo のパスワードを求められたら、このターミナルで入力してください。")

        update_result = cls.run_install_command(["sudo", "apt-get", "update"])
        if update_result != 0:
            return update_result

        return cls.run_install_command(["sudo", "apt-get", "install", "-y", "adb"])
