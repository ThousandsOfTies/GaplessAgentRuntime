from __future__ import annotations

import platform
import shutil

from scripts.gar_lib.environments.base import EnvironmentSetupOption
from scripts.gar_lib.environments.install import print_user_terminal_handoff, sudo_block_reason


class GitHubCodespacesEnvironment(EnvironmentSetupOption):
    provider_id = "github_codespaces"
    display_name = "GitHub Codespaces"
    description = "GitHub CLI を使って Codespaces に接続します"
    display_order = 10
    required_commands = ("gh", "sshfs")

    @classmethod
    def install_hint(cls, missing: list[str]) -> str:
        supported_missing = [
            command
            for command in missing
            if command in ("gh", "sshfs")
        ]
        if not supported_missing:
            return super().install_hint(missing)

        missing_text = ", ".join(supported_missing)
        if _is_wsl_or_linux():
            install_command = "sudo apt-get install -y " + " ".join(supported_missing)
            return (
                f"不足: {missing_text}\n"
                "Debian/Ubuntu/WSL では次のコマンドを実行してください。\n"
                f"`sudo apt-get update && {install_command}`"
            )

        return f"不足: {missing_text}\nGitHub CLI / sshfs をインストールしてください。"

    @classmethod
    def install_dependencies(cls, missing: list[str]) -> int:
        installable = [command for command in missing if command in ("gh", "sshfs")]
        if not installable:
            print(cls.install_hint(missing))
            return 1

        if not _is_wsl_or_linux() or shutil.which("apt-get") is None:
            print(cls.install_hint(missing))
            return 1

        blocked = sudo_block_reason()
        if blocked:
            print_user_terminal_handoff(
                "GitHub Codespaces 連携ツールのインストールには sudo が必要です。",
                [
                    "sudo apt-get update",
                    "sudo apt-get install -y " + " ".join(installable),
                ],
                reason=blocked,
            )
            return 1

        print("GitHub Codespaces 連携ツールを apt-get でインストールします。")
        print("sudo のパスワードを求められたら、このターミナルで入力してください。")

        update_result = cls.run_install_command(["sudo", "apt-get", "update"])
        if update_result != 0:
            return update_result

        return cls.run_install_command(["sudo", "apt-get", "install", "-y", *installable])


def _is_wsl_or_linux() -> bool:
    release = platform.release().lower()
    return platform.system() == "Linux" or "microsoft" in release
