"""Shared recovery guidance for AWS-backed SSH connection failures."""

from __future__ import annotations

import shlex
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from scripts.gar_lib.commands.terminal import run_terminal_request
from scripts.gar_lib.config import default_ec2_region, load_config


@dataclass
class SshRecoveryContext:
    command_label: str
    restart_command: str | None = None
    retry_command: str | None = None
    reported: bool = False


_SSH_RECOVERY_CONTEXT: ContextVar[SshRecoveryContext | None] = ContextVar(
    "gar_ssh_recovery_context", default=None
)


@contextmanager
def ssh_connection_recovery_context(
    command_label: str,
    *,
    workspace: str | None = None,
) -> Iterator[None]:
    """Attach operation-specific retry guidance to SSH provider calls."""
    quoted_workspace = f" --workspace {shlex.quote(workspace)}" if workspace else ""
    context = SshRecoveryContext(
        command_label=command_label,
        restart_command=f"gar sim start{quoted_workspace}",
        retry_command=f"{command_label}{quoted_workspace}",
    )
    token = _SSH_RECOVERY_CONTEXT.set(context)
    try:
        yield
    finally:
        _SSH_RECOVERY_CONTEXT.reset(token)


def handle_ssh_connection_failure(host: str, returncode: int) -> None:
    """Send AWS login to Terminal Bridge after an OpenSSH connection failure.

    OpenSSH reserves exit code 255 for transport/authentication failures. Other
    remote command errors are left untouched, so a failed application command
    does not incorrectly prompt the user to log in to AWS.
    """
    if returncode != 255:
        return

    context = _SSH_RECOVERY_CONTEXT.get()
    if context is not None and context.reported:
        return
    if context is not None:
        context.reported = True

    command_label = context.command_label if context else "gar"
    config = load_config()
    region = default_ec2_region(config)
    print(f"{command_label}: {host} への SSH/scp 接続に失敗しました。", file=sys.stderr)
    print(
        "  ConnectTimeout により中断しました。EC2 の停止、AWS 認証切れ、"
        "または起動後の Public IP 未更新を確認してください。",
        file=sys.stderr,
    )
    if not region:
        print(
            "  AWS region が未設定です。`gar setup` で SSH Remote の EC2 region を設定してから再実行してください。",
            file=sys.stderr,
        )
        return

    request_result = run_terminal_request(
        command_parts=["aws", "login", "--remote", "--region", region],
        title="GAR: AWS ログイン（SSH 接続を復旧）",
        cwd=None,
    )
    if request_result == 0:
        print(
            "  VS Code Terminal Bridge に AWS ログインを送信しました。表示された URL をブラウザで開き、"
            "認証コードはその terminal に入力してください。",
            file=sys.stderr,
        )
    else:
        print(
            "  VS Code Terminal Bridge の要求作成に失敗しました。通常の VS Code terminal で次を実行してください。",
            file=sys.stderr,
        )
        print(f"    aws login --remote --region {region}", file=sys.stderr)

    if context is not None:
        print(f"  認証後: {context.restart_command}", file=sys.stderr)
        print(f"  起動完了後に再実行: {context.retry_command}", file=sys.stderr)
    else:
        print("  認証・EC2 起動後に、失敗した gar コマンドを再実行してください。", file=sys.stderr)
