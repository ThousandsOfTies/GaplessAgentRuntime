from __future__ import annotations

from agp.environments.base import DevEnvironment


class SshRemoteEnvironment(DevEnvironment):
    provider_id = "ssh_remote"
    display_name = "SSH Remote"
    description = "ssh コマンドで任意のリモート環境に接続します"
    display_order = 30
    required_commands = ("ssh",)

    @classmethod
    def install_hint(cls, missing: list[str]) -> str:
        commands = ", ".join(missing)
        return f"不足: {commands}\nOpenSSH client をインストールしてください。"
