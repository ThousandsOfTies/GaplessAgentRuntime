"""CLI の接続失敗を、人間が次にやるべきことへ翻訳して報告する。"""

from __future__ import annotations

import shlex
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from scripts.gar_lib.core.errors import AccessConnectionError
from scripts.gar_lib.core.workspace import Workspace


@dataclass(frozen=True)
class RecoveryAction:
    title: str
    terminal_command: tuple[str, ...] | None
    instructions: tuple[str, ...]


def report_access_failure(
    error: AccessConnectionError,
    *,
    workspace: Workspace,
    retry_command: str,
    purpose: str = "simulation",
    run_terminal: Callable[..., int] | None = None,
) -> int:
    """接続失敗を stderr へ報告し、必要なら見える terminal で復旧コマンドを走らせる。

    terminalへの実際の起動は行わず、呼び出し側が渡した `run_terminal`（例:
    `commands.terminal.run_terminal_run_command`）へ委譲する。これにより、この共有
    adapter と個別 command runner の間に循環依存を作らない。
    """

    action = plan_access_recovery(error, workspace=workspace, retry_command=retry_command, purpose=purpose)
    if action.terminal_command is not None and run_terminal is not None:
        run_terminal(
            command_parts=[],
            command_text=shlex.join(action.terminal_command),
            title=action.title,
            cwd=str(Path.cwd()),
        )
    print(f"gar: {error}", file=sys.stderr)
    for instruction in action.instructions:
        print(f"  {instruction}", file=sys.stderr)
    return 1


def plan_access_recovery(
    error: AccessConnectionError,
    *,
    workspace: Workspace,
    retry_command: str,
    purpose: str = "simulation",
) -> RecoveryAction:
    """失敗した channel と理由から、復旧手順を組み立てる。"""

    if error.channel == "aws":
        region = workspace.ec2.region
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
        if error.reason == "target_prepare_required":
            return RecoveryAction(
                title="GAR: Target lifecycle権限の準備",
                terminal_command=("gar", "target", "prepare", "--workspace", workspace.name),
                instructions=(
                    "表示されたterminalでTarget recipeのsudo認証を完了してください。",
                    f"準備完了後に再実行: {retry_command}",
                ),
            )
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
        if purpose == "target":
            return RecoveryAction(
                title="GAR: 実機SSH接続の復旧",
                terminal_command=None,
                instructions=(
                    "実機が起動していることと、SSH configのHost・User・接続経路を確認してください。",
                    f"確認後に再実行: {retry_command}",
                ),
            )
        region = workspace.ec2.region
        if not isinstance(region, str) or not region:
            return RecoveryAction(
                title="GAR: simulation接続の復旧",
                terminal_command=None,
                instructions=(
                    "AWS regionが未設定です。gar configでsimulation環境を設定してください。",
                    f"設定後に再実行: {retry_command}",
                ),
            )
        workspace_arg = shlex.quote(workspace.name)
        return RecoveryAction(
            title="GAR: AWSログイン（simulation接続を復旧）",
            terminal_command=("aws", "login", "--remote", "--region", region),
            instructions=(
                "表示されたURLをブラウザで開き、認証コードはそのterminalに入力してください。",
                f"認証後: gar sim start host --workspace {workspace_arg}",
                f"起動完了後に再実行: {retry_command}",
            ),
        )

    if error.channel == "docker":
        if error.reason == "daemon":
            return RecoveryAction(
                title="GAR: Docker daemonの復旧",
                terminal_command=None,
                instructions=(
                    "Docker daemonが動作しているか確認してください（Docker Desktopの起動、"
                    "またはsudo systemctl start docker）。",
                    "現在のユーザーがdockerグループに所属しているかも確認してください。",
                    f"復旧後に再実行: {retry_command}",
                ),
            )
        workspace_arg = shlex.quote(workspace.name)
        return RecoveryAction(
            title="GAR: simulation containerの起動",
            terminal_command=None,
            instructions=(
                f"container {error.endpoint} が起動していません。",
                f"起動: gar sim start host --workspace {workspace_arg}",
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
