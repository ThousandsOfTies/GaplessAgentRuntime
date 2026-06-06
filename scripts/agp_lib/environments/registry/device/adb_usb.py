from __future__ import annotations

import platform
import shutil

from scripts.agp_lib.environments.base import DevEnvironment


class AdbUsbEnvironment(DevEnvironment):
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

        sudo_block_reason = cls.sudo_block_reason()
        if sudo_block_reason:
            cls.print_user_terminal_handoff(
                "adb のインストールには sudo が必要です。",
                [
                    "sudo apt-get update",
                    "sudo apt-get install -y adb",
                ],
                reason=sudo_block_reason,
            )
            return 1

        print("adb を apt-get でインストールします。")
        print("sudo のパスワードを求められたら、このターミナルで入力してください。")

        update_result = cls.run_subprocess(["sudo", "apt-get", "update"])
        if update_result != 0:
            return update_result

        return cls.run_subprocess(["sudo", "apt-get", "install", "-y", "adb"])


    @classmethod
    def run_remote(cls, target: str, command: str, *, capture_output: bool = False, text: bool = True, check: bool = False):
        import subprocess
        cmd = ["adb"]
        if target:
            cmd.extend(["-s", target])
        cmd.extend(["shell", command])
        return subprocess.run(cmd, capture_output=capture_output, text=text, check=check)

    @classmethod
    def push_file(cls, target: str, src, dest) -> int:
        import subprocess
        cmd = ["adb"]
        if target:
            cmd.extend(["-s", target])
        cmd.extend(["push", str(src), str(dest)])
        return subprocess.run(cmd, check=False).returncode

    @classmethod
    def pull_file(cls, target: str, src, dest) -> int:
        import subprocess
        cmd = ["adb"]
        if target:
            cmd.extend(["-s", target])
        cmd.extend(["pull", str(src), str(dest)])
        return subprocess.run(cmd, check=False).returncode
