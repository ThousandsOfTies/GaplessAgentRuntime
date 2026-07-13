from __future__ import annotations

from scripts.gar_lib.environments.base import EnvironmentSetupOption


class SshRemoteEnvironment(EnvironmentSetupOption):
    provider_id = "ssh_remote"
    display_name = "SSH Remote"
    description = "AWS EC2 を使う場合はこれを選択します。SSH config 経由で任意のリモート環境にも接続できます"
    display_order = 30
    required_commands = ("ssh",)

    @classmethod
    def install_hint(cls, missing: list[str]) -> str:
        commands = ", ".join(missing)
        return f"不足: {commands}\nOpenSSH client をインストールしてください。"
