from __future__ import annotations

import platform
import shutil
import tempfile
from pathlib import Path

from scripts.agp_lib.environments.base import DevEnvironment


class AwsSsmEnvironment(DevEnvironment):
    provider_id = "aws_ssm"
    display_name = "AWS SSM"
    description = "AWS CLI と Session Manager Plugin で EC2 に接続します"
    display_order = 20
    required_commands = ("aws", "session-manager-plugin")

    @classmethod
    def install_hint(cls, missing: list[str]) -> str:
        commands = ", ".join(missing)
        return (
            f"不足: {commands}\n"
            "AWS CLI v2 と Session Manager Plugin をインストールしてください。"
        )

    @classmethod
    def install_dependencies(cls, missing: list[str]) -> int:
        unsupported = _unsupported_reason()
        if unsupported:
            print(cls.install_hint(missing))
            print(unsupported)
            return 1

        sudo_block_reason = cls.sudo_block_reason()
        if sudo_block_reason:
            cls.print_user_terminal_handoff(
                "AWS SSM 接続ツールのインストールには sudo が必要です。",
                _manual_install_commands(missing),
                reason=sudo_block_reason,
            )
            return 1

        helper_result = _ensure_helper_commands()
        if helper_result != 0:
            return helper_result

        with tempfile.TemporaryDirectory(prefix="agp-aws-ssm-") as tmp:
            work_dir = Path(tmp)

            if "aws" in missing:
                result = _install_aws_cli(work_dir)
                if result != 0:
                    return result

            if "session-manager-plugin" in missing:
                result = _install_session_manager_plugin(work_dir)
                if result != 0:
                    return result

        return 0


def _unsupported_reason() -> str | None:
    if platform.system() != "Linux":
        return "自動インストールは Linux のみ対応です。"
    if _arch_id() is None:
        return f"未対応の CPU アーキテクチャです: {platform.machine()}"
    return None


def _ensure_helper_commands() -> int:
    missing_helpers = [
        command
        for command in ("curl", "unzip")
        if shutil.which(command) is None
    ]
    if not missing_helpers:
        return 0

    if shutil.which("apt-get") is None:
        print("curl / unzip が不足しています。先にインストールしてください。")
        return 1

    print("インストール補助コマンドを apt-get でインストールします:")
    for command in missing_helpers:
        print(f"  - {command}")

    update_result = AwsSsmEnvironment.run_subprocess(["sudo", "apt-get", "update"])
    if update_result != 0:
        return update_result

    return AwsSsmEnvironment.run_subprocess(
        ["sudo", "apt-get", "install", "-y", *missing_helpers]
    )


def _install_aws_cli(work_dir: Path) -> int:
    arch = _arch_id()
    if arch is None:
        return 1

    zip_path = work_dir / "awscliv2.zip"
    url = f"https://awscli.amazonaws.com/awscli-exe-linux-{arch}.zip"

    print("AWS CLI v2 をインストールします。")
    result = AwsSsmEnvironment.run_subprocess(
        ["curl", url, "-o", str(zip_path)]
    )
    if result != 0:
        return result

    result = AwsSsmEnvironment.run_subprocess(
        ["unzip", "-q", str(zip_path), "-d", str(work_dir)]
    )
    if result != 0:
        return result

    return AwsSsmEnvironment.run_subprocess(
        ["sudo", str(work_dir / "aws" / "install")]
    )


def _install_session_manager_plugin(work_dir: Path) -> int:
    arch = _arch_id()
    if arch is None:
        return 1

    deb_path = work_dir / "session-manager-plugin.deb"
    deb_arch = "ubuntu_arm64" if arch == "aarch64" else "ubuntu_64bit"
    url = (
        "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/"
        f"{deb_arch}/session-manager-plugin.deb"
    )

    print("Session Manager Plugin をインストールします。")
    result = AwsSsmEnvironment.run_subprocess(
        ["curl", url, "-o", str(deb_path)]
    )
    if result != 0:
        return result

    return AwsSsmEnvironment.run_subprocess(
        ["sudo", "dpkg", "-i", str(deb_path)]
    )


def _arch_id() -> str | None:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    if machine in ("aarch64", "arm64"):
        return "aarch64"
    return None


def _manual_install_commands(missing: list[str]) -> list[str]:
    arch = _arch_id()
    if arch is None:
        return []

    commands = [
        "sudo apt-get update",
        "sudo apt-get install -y curl unzip",
        'AGP_TMP="$(mktemp -d)"',
    ]

    if "aws" in missing:
        commands.extend(
            [
                f'curl "https://awscli.amazonaws.com/awscli-exe-linux-{arch}.zip" -o "$AGP_TMP/awscliv2.zip"',
                'unzip -q "$AGP_TMP/awscliv2.zip" -d "$AGP_TMP"',
                'sudo "$AGP_TMP/aws/install"',
            ]
        )

    if "session-manager-plugin" in missing:
        deb_arch = "ubuntu_arm64" if arch == "aarch64" else "ubuntu_64bit"
        commands.extend(
            [
                "curl "
                '"https://s3.amazonaws.com/session-manager-downloads/plugin/latest/'
                f'{deb_arch}/session-manager-plugin.deb" '
                '-o "$AGP_TMP/session-manager-plugin.deb"',
                'sudo dpkg -i "$AGP_TMP/session-manager-plugin.deb"',
            ]
        )

    commands.append('rm -rf "$AGP_TMP"')
    return commands
