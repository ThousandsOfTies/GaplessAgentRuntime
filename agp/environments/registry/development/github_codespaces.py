from __future__ import annotations

import platform
import shutil

from agp.environments.base import DevEnvironment


class GitHubCodespacesEnvironment(DevEnvironment):
    provider_id = "github_codespaces"
    display_name = "GitHub Codespaces"
    description = "GitHub CLI を使って Codespaces に接続します"
    display_order = 10
    required_commands = ("gh",)

    @classmethod
    def install_hint(cls, missing: list[str]) -> str:
        if "gh" not in missing:
            return super().install_hint(missing)

        if _is_wsl_or_linux():
            return (
                "不足: gh\n"
                "Debian/Ubuntu/WSL では GitHub CLI の apt リポジトリを追加して "
                "`sudo apt install gh` を実行してください。"
            )

        return "不足: gh\nGitHub CLI をインストールしてください。"

    @classmethod
    def install_dependencies(cls, missing: list[str]) -> int:
        if "gh" not in missing:
            print(cls.install_hint(missing))
            return 1

        if not _is_wsl_or_linux() or shutil.which("apt-get") is None:
            print(cls.install_hint(missing))
            return 1

        sudo_block_reason = cls.sudo_block_reason()
        if sudo_block_reason:
            cls.print_user_terminal_handoff(
                "GitHub CLI のインストールには sudo が必要です。",
                [
                    "sudo apt-get update",
                    "sudo apt-get install -y gh",
                ],
                reason=sudo_block_reason,
            )
            return 1

        print("GitHub CLI を apt-get でインストールします。")
        print("sudo のパスワードを求められたら、このターミナルで入力してください。")

        update_result = cls.run_subprocess(["sudo", "apt-get", "update"])
        if update_result != 0:
            return update_result

        return cls.run_subprocess(["sudo", "apt-get", "install", "-y", "gh"])

    @classmethod
    def login(cls) -> int:
        return cls.run_subprocess(["gh", "auth", "login"])

    @classmethod
    def list_instances(cls) -> int:
        return cls.run_subprocess(["gh", "codespace", "list"])

    @classmethod
    def shell(cls, target: str | None = None) -> int:
        argv = ["gh", "codespace", "ssh"]
        if target:
            argv.extend(["-c", target])
        return cls.run_subprocess(argv)


def _is_wsl_or_linux() -> bool:
    release = platform.release().lower()
    return platform.system() == "Linux" or "microsoft" in release
