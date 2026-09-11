"""Run a Target-owned one-time recipe over SSH."""

from __future__ import annotations

import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from scripts.gar_lib.access.display import run_displayed
from scripts.gar_lib.access.ssh import SSH_CONNECTION_OPTIONS
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.output import JSON_OUTPUT


def prepare_ssh_target(
    host: str,
    recipe: Path,
    *,
    target_id: str,
    recipe_version: str,
    gar_tools_commit: str,
    config_path: Path | None = None,
    include_lifecycle: bool = False,
) -> None:
    """Stage and run a validated Target recipe, asking for sudo when it needs it."""

    identity_payload = _recipe_identity_payload(
        target_id=target_id,
        recipe_version=recipe_version,
        gar_tools_commit=gar_tools_commit,
    )
    with tempfile.TemporaryDirectory(prefix="gar-target-recipe-") as temporary:
        identity_source = Path(temporary) / "recipe-version"
        identity_source.write_text(identity_payload, encoding="utf-8")
        identity_source.chmod(0o600)
        _prepare_ssh_target(
            host,
            recipe,
            identity_source,
            config_path=config_path,
            include_lifecycle=include_lifecycle,
        )


def _prepare_ssh_target(
    host: str,
    recipe: Path,
    identity_source: Path,
    *,
    config_path: Path | None,
    include_lifecycle: bool,
) -> None:
    config = config_path or Path.home() / ".ssh" / "config"
    prepare_script = recipe / "prepare.sh"
    installer = recipe / "gar-target-install"
    service_template = recipe / "gar-app@.service"
    lifecycle = recipe / "gar-target-lifecycle"
    payloads = (
        prepare_script,
        installer,
        service_template,
        *((lifecycle,) if include_lifecycle else ()),
        identity_source,
    )
    for payload in payloads:
        if payload.is_symlink() or not payload.is_file():
            raise GarDomainError(f"target prepare recipeの必須fileがありません: {payload}")
    user_result = subprocess.run(
        ("ssh", "-F", str(config), *SSH_CONNECTION_OPTIONS, "-o", f"HostKeyAlias={host}", host, "id -un"),
        check=False,
        capture_output=True,
        text=True,
    )
    if user_result.returncode != 0:
        detail = user_result.stderr.strip() or "SSH接続に失敗しました"
        raise GarDomainError(f"target prepare: {detail}")
    remote_user = user_result.stdout.strip()
    if not remote_user or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in remote_user
    ):
        raise GarDomainError("target prepare: SSH接続ユーザー名を安全に取得できません")

    if JSON_OUTPUT.get() and remote_user != "root":
        privilege = subprocess.run(
            (
                "ssh",
                "-T",
                "-F",
                str(config),
                *SSH_CONNECTION_OPTIONS,
                "-o",
                f"HostKeyAlias={host}",
                host,
                "sudo -n /bin/sh -c true",
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        if privilege.returncode != 0:
            raise GarDomainError(
                "target prepare --jsonには非対話sudo権限が必要です。対話認証はJSONなしで実行してください"
            )

    stage = f"/tmp/gar-prepare-{uuid4().hex}"
    create = subprocess.run(
        (
            "ssh",
            "-F",
            str(config),
            *SSH_CONNECTION_OPTIONS,
            "-o",
            f"HostKeyAlias={host}",
            host,
            f"mkdir -m 0700 {shlex.quote(stage)}",
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    if create.returncode != 0:
        detail = create.stderr.strip() or "一時directoryを作成できません"
        raise GarDomainError(f"target prepare: {detail}")

    try:
        copied = subprocess.run(
            (
                "scp",
                "-F",
                str(config),
                *SSH_CONNECTION_OPTIONS,
                "-o",
                f"HostKeyAlias={host}",
                *(str(payload) for payload in payloads),
                f"{host}:{stage}/",
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        if copied.returncode != 0:
            detail = copied.stderr.strip() or "recipeを転送できません"
            raise GarDomainError(f"target prepare: {detail}")

        remote = (
            f"/bin/sh {shlex.quote(stage + '/prepare.sh')} "
            f"{shlex.quote(remote_user)} {shlex.quote(stage + '/gar-target-install')} "
            f"{shlex.quote(stage + '/gar-app@.service')}"
        )
        if include_lifecycle:
            remote += f" {shlex.quote(stage + '/gar-target-lifecycle')}"
        remote += f" {shlex.quote(stage + '/recipe-version')}"
        if JSON_OUTPUT.get() and remote_user != "root":
            remote = "sudo -n " + remote
        result = run_displayed(
            (
                "ssh",
                "-T" if JSON_OUTPUT.get() else "-tt",
                "-F",
                str(config),
                *SSH_CONNECTION_OPTIONS,
                "-o",
                f"HostKeyAlias={host}",
                host,
                remote,
            ),
            runner=subprocess.run,
            check=False,
        )
        if result.returncode != 0:
            raise GarDomainError("target prepare: Target recipeの実行に失敗しました")
    finally:
        subprocess.run(
            (
                "ssh",
                "-F",
                str(config),
                *SSH_CONNECTION_OPTIONS,
                "-o",
                f"HostKeyAlias={host}",
                host,
                f"rm -rf -- {shlex.quote(stage)}",
            ),
            check=False,
            capture_output=True,
            text=True,
        )


def _recipe_identity_payload(
    *,
    target_id: str,
    recipe_version: str,
    gar_tools_commit: str,
) -> str:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", target_id) is None:
        raise GarDomainError("target prepare: recipe identityのtarget IDが不正です")
    if re.fullmatch(r"[1-9][0-9]*", recipe_version) is None:
        raise GarDomainError("target prepare: recipe identityのversionが不正です")
    if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64}|sha256:[0-9a-f]{64})", gar_tools_commit) is None:
        raise GarDomainError("target prepare: recipe identityのgar-tools commitが不正です")
    return f"target_id={target_id}\n" f"recipe_version={recipe_version}\n" f"gar_tools_commit={gar_tools_commit}\n"
