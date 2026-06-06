from __future__ import annotations

from scripts.agp_lib.environments.base import DevEnvironment


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

    @classmethod
    def start_port_forward(cls, target: str) -> int:
        import subprocess

        from scripts.agp_lib._config import PROJECT_ROOT
        return subprocess.run(
            [str(PROJECT_ROOT / "tools" / "forward_ec2_ports.sh"), "--host", target],
            check=False,
        ).returncode

    @classmethod
    def stop_port_forward(cls, target: str) -> int:
        import subprocess

        from scripts.agp_lib._config import PROJECT_ROOT
        return subprocess.run(
            [str(PROJECT_ROOT / "tools" / "forward_ec2_ports.sh"), "--host", target, "--stop"],
            check=False,
        ).returncode

    @classmethod
    def status_port_forward(cls, target: str) -> int:
        import subprocess

        from scripts.agp_lib._config import PROJECT_ROOT
        return subprocess.run(
            [str(PROJECT_ROOT / "tools" / "forward_ec2_ports.sh"), "--host", target, "--status"],
            check=False,
        ).returncode

    @classmethod
    def interactive_shell_script(cls, target: str) -> str:
        import shlex
        quoted_host = shlex.quote(target)
        return f"""#!/usr/bin/env bash
set -euo pipefail

exec ssh -F "$HOME/.ssh/config" -t {quoted_host} "cd ~ && exec bash -l"
"""
