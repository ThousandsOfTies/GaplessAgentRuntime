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


    @classmethod
    def run_remote(cls, target: str, command: str, *, capture_output: bool = False, text: bool = True, check: bool = False):
        import subprocess
        from pathlib import Path
        config_arg = str(Path.home() / ".ssh" / "config")
        cmd = ["ssh", "-F", config_arg, target, command]
        return subprocess.run(cmd, capture_output=capture_output, text=text, check=check)

    @classmethod
    def push_file(cls, target: str, src, dest) -> int:
        import subprocess
        from pathlib import Path
        config_arg = str(Path.home() / ".ssh" / "config")
        cmd = ["scp", "-F", config_arg, "-r", str(src), f"{target}:{dest}"]
        return subprocess.run(cmd, check=False).returncode

    @classmethod
    def pull_file(cls, target: str, src, dest) -> int:
        import subprocess
        from pathlib import Path
        config_arg = str(Path.home() / ".ssh" / "config")
        cmd = ["scp", "-F", config_arg, "-r", f"{target}:{src}", str(dest)]
        return subprocess.run(cmd, check=False).returncode
