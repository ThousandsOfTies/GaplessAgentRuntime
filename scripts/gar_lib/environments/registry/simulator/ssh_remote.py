from __future__ import annotations

from scripts.gar_lib.environments.base import DevEnvironment
from scripts.gar_lib.environments.ssh_recovery import handle_ssh_connection_failure

SSH_CONNECTION_OPTIONS = (
    "-o", "ConnectTimeout=10",
    "-o", "ConnectionAttempts=1",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=3",
)


class SshRemoteEnvironment(DevEnvironment):
    provider_id = "ssh_remote"
    display_name = "SSH Remote"
    description = "AWS EC2 を使う場合はこれを選択します。SSH config 経由で任意のリモート環境にも接続できます"
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
        cmd = ["ssh", "-F", config_arg, *SSH_CONNECTION_OPTIONS, target, command]
        result = subprocess.run(cmd, capture_output=capture_output, text=text, check=check)
        handle_ssh_connection_failure(target, result.returncode)
        return result

    @classmethod
    def push_file(cls, target: str, src, dest) -> int:
        import subprocess
        from pathlib import Path
        config_arg = str(Path.home() / ".ssh" / "config")
        cmd = ["scp", "-F", config_arg, *SSH_CONNECTION_OPTIONS, "-r", str(src), f"{target}:{dest}"]
        result = subprocess.run(cmd, check=False)
        handle_ssh_connection_failure(target, result.returncode)
        return result.returncode

    @classmethod
    def pull_file(cls, target: str, src, dest) -> int:
        import subprocess
        from pathlib import Path
        config_arg = str(Path.home() / ".ssh" / "config")
        cmd = ["scp", "-F", config_arg, *SSH_CONNECTION_OPTIONS, "-r", f"{target}:{src}", str(dest)]
        result = subprocess.run(cmd, check=False)
        handle_ssh_connection_failure(target, result.returncode)
        return result.returncode

    @classmethod
    def start_port_forward(cls, target: str) -> int:
        import subprocess

        from scripts.gar_lib.config import PROJECT_ROOT
        return subprocess.run(
            [str(PROJECT_ROOT / "tools" / "forward_ec2_ports.sh"), "--host", target],
            check=False,
        ).returncode

    @classmethod
    def stop_port_forward(cls, target: str) -> int:
        import subprocess

        from scripts.gar_lib.config import PROJECT_ROOT
        return subprocess.run(
            [str(PROJECT_ROOT / "tools" / "forward_ec2_ports.sh"), "--host", target, "--stop"],
            check=False,
        ).returncode

    @classmethod
    def status_port_forward(cls, target: str) -> int:
        import subprocess

        from scripts.gar_lib.config import PROJECT_ROOT
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

    @classmethod
    def host_command(
        cls,
        command: str,
        *,
        host: str | None = None,
        instance_id: str | None = None,
        region: str | None = None,
        update_ssh: bool = True,
        pull: bool = False,
        json_output: bool = False,
    ) -> int:
        from scripts.gar_lib.environments.registry.simulator.aws_ec2 import run_ec2_command

        return run_ec2_command(
            command,
            host=host,
            instance_id=instance_id,
            region=region,
            update_ssh=update_ssh,
            pull=pull,
            json_output=json_output,
        )
