from __future__ import annotations

import getpass
import platform
import shutil

from scripts.gar_lib.environments.base import DevEnvironment


class LocalEnvironment(DevEnvironment):
    provider_id = "local"
    display_name = "Local Docker"
    description = "このマシン上のローカル Docker/devcontainer 環境を使います"
    display_order = 5
    required_commands = ("docker",)

    @classmethod
    def install_hint(cls, missing: list[str]) -> str:
        supported_missing = [
            command
            for command in missing
            if command == "docker"
        ]
        if not supported_missing:
            return super().install_hint(missing)

        if _is_wsl_or_linux():
            return (
                "不足: docker\n"
                "Debian/Ubuntu/WSL では次のコマンドを実行してください。\n"
                "`sudo apt-get update && sudo apt-get install -y docker.io && "
                "sudo groupadd -f docker && sudo usermod -aG docker $USER`\n"
                "必要に応じて Docker daemon を起動してください: "
                "`sudo service docker start`\n"
                "docker group の反映にはログアウト/再ログインが必要です。"
            )

        return "不足: docker\nDocker Desktop または Docker Engine をインストールしてください。"

    @classmethod
    def install_dependencies(cls, missing: list[str]) -> int:
        installable = [command for command in missing if command == "docker"]
        if not installable:
            print(cls.install_hint(missing))
            return 1

        if not _is_wsl_or_linux() or shutil.which("apt-get") is None:
            print(cls.install_hint(missing))
            return 1

        sudo_block_reason = cls.sudo_block_reason()
        if sudo_block_reason:
            cls.print_user_terminal_handoff(
                "Local Docker のインストールには sudo が必要です。",
                [
                    "sudo apt-get update",
                    "sudo apt-get install -y docker.io",
                    "sudo groupadd -f docker",
                    "sudo usermod -aG docker $USER",
                    "sudo service docker start || true",
                ],
                reason=sudo_block_reason,
            )
            return 1

        print("Local Docker を apt-get でインストールします。")
        print("sudo のパスワードを求められたら、このターミナルで入力してください。")

        update_result = cls.run_subprocess(["sudo", "apt-get", "update"])
        if update_result != 0:
            return update_result

        install_result = cls.run_subprocess(["sudo", "apt-get", "install", "-y", "docker.io"])
        if install_result != 0:
            return install_result

        group_result = cls.run_subprocess(["sudo", "groupadd", "-f", "docker"])
        if group_result != 0:
            return group_result

        user_result = cls.run_subprocess(["sudo", "usermod", "-aG", "docker", getpass.getuser()])
        if user_result != 0:
            return user_result

        cls.run_subprocess(["sudo", "service", "docker", "start"])
        print("docker group の反映にはログアウト/再ログインが必要です。")
        return 0

    @classmethod
    def code_command(
        cls,
        command: str,
        *,
        target: str | None = None,
        remote_path: str | None = None,
        mount_dir: str | None = None,
        settings: str | None = None,
        profile_name: str | None = None,
        no_mount: bool = False,
        shutdown: bool = False,
        timeout: int | None = None,
    ) -> int:
        del target, remote_path, mount_dir, settings, profile_name, no_mount, shutdown, timeout
        if command in ("boot", "start"):
            print("Local development environment is already available.")
            return 0
        if command in ("stop", "shutdown"):
            print("Local development environment does not need to be stopped.")
            return 0
        if command == "status":
            print("Local development environment: available")
            return 0

        raise NotImplementedError(f"{cls.__name__} does not implement gar code {command}")


def _is_wsl_or_linux() -> bool:
    release = platform.release().lower()
    return platform.system() == "Linux" or "microsoft" in release
