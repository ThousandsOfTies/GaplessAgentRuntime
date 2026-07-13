"""Turn structured access failures into user-actionable recovery plans."""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from scripts.gar_lib.core.errors import AccessConnectionError
from scripts.gar_lib.core.workspace import Workspace


@dataclass(frozen=True)
class RecoveryAction:
    title: str
    terminal_command: tuple[str, ...] | None
    instructions: tuple[str, ...]


class AccessRecoveryPlanner:
    def plan(
        self,
        error: AccessConnectionError,
        *,
        workspace: Workspace,
        retry_command: str,
    ) -> RecoveryAction:
        if error.channel == "aws":
            region = workspace.ec2.get("region")
            if not isinstance(region, str) or not region:
                region = error.endpoint
            return RecoveryAction(
                title="GAR: AWSログイン（simulation host操作を復旧）",
                terminal_command=("aws", "login", "--remote", "--region", region),
                instructions=(
                    "表示されたURLをブラウザで開き、認証コードはそのterminalに入力してください。",
                    f"認証後に再実行: {retry_command}",
                ),
            )

        if error.channel in {"ssh", "scp"}:
            if error.reason == "host_key_verification":
                return RecoveryAction(
                    title="GAR: SSH host keyの確認",
                    terminal_command=None,
                    instructions=(
                        "SSH host keyを確認し、古いknown_hostsエントリがあれば削除してください。",
                        f"確認後に再実行: {retry_command}",
                    ),
                )
            if error.reason == "ssh_authentication":
                return RecoveryAction(
                    title="GAR: SSH鍵の確認",
                    terminal_command=None,
                    instructions=(
                        "SSH configのUserとIdentityFile、および秘密鍵の権限を確認してください。",
                        f"確認後に再実行: {retry_command}",
                    ),
                )
            region = workspace.ec2.get("region")
            if not isinstance(region, str) or not region:
                return RecoveryAction(
                    title="GAR: simulation接続の復旧",
                    terminal_command=None,
                    instructions=(
                        "AWS regionが未設定です。gar setupでsimulation環境を設定してください。",
                        f"設定後に再実行: {retry_command}",
                    ),
                )
            workspace_arg = shlex.quote(workspace.name)
            return RecoveryAction(
                title="GAR: AWSログイン（simulation接続を復旧）",
                terminal_command=("aws", "login", "--remote", "--region", region),
                instructions=(
                    "表示されたURLをブラウザで開き、認証コードはそのterminalに入力してください。",
                    f"認証後: gar sim start --workspace {workspace_arg}",
                    f"起動完了後に再実行: {retry_command}",
                ),
            )

        if error.channel == "adb":
            return RecoveryAction(
                title="GAR: ADB接続の復旧",
                terminal_command=None,
                instructions=(
                    "gar usb listでデバイス状態を確認してください。",
                    "必要ならgar usb attachでデバイスをWSLへ接続してください。",
                    f"接続後に再実行: {retry_command}",
                ),
            )

        return RecoveryAction(
            title="GAR: 接続の復旧",
            terminal_command=None,
            instructions=(
                f"{error.channel}で{error.endpoint}へ接続できませんでした: {error.reason}",
                f"接続を復旧後に再実行: {retry_command}",
            ),
        )
