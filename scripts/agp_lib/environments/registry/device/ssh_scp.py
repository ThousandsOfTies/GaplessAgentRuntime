from __future__ import annotations

from scripts.agp_lib.environments.base import DevEnvironment


class SshScpEnvironment(DevEnvironment):
    provider_id = "ssh_scp"
    display_name = "SSH / scp"
    description = (
        "ssh / scp でネットワーク越しに実機へ接続します"
        "（adb が使えない / 既に SSH 経路が整っている環境向け）"
    )
    display_order = 20
    required_commands = ("ssh", "scp")

    @classmethod
    def install_hint(cls, missing: list[str]) -> str:
        commands = ", ".join(missing)
        return (
            f"不足: {commands}\n"
            "OpenSSH client をインストールしてください。"
            " 実機側にも sshd が起動している必要があります。"
        )
