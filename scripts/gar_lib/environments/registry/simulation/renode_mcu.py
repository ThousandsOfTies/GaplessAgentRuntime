"""Renode MCU simulation provider.

`gar setup` のシミュレート環境の選択肢として Renode を提供する。

Renode は VM ではなく機能的シミュレータ（命令セットエミュレータ）で、
Cortex-M / RISC-V などの MCU ファームウェアを未改変のまま仮想実行できる。
これにより、現行 PoC の「同一バイナリを sim と実機で動かす」価値を、
Linux SBC だけでなく MCU / ベアメタル領域へ拡張できる。

本ファイルが担うのは第一弾として「setup で選択 → Renode を導入 → 検証」まで。
`gar sim env` ランタイムを Renode 上で回す統合（.resc 生成・ペリフェラル
モデルの起動など）は今後の作業で、現時点ではランタイム系メソッドは
未配線であることを明示するスタブにしている（既存の ssh_remote を使うこと）。
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from scripts.gar_lib.environments.base import DevEnvironment

RENODE_RELEASES_API = "https://api.github.com/repos/renode/renode/releases/latest"
RENODE_RELEASES_PAGE = "https://github.com/renode/renode/releases/latest"
RENODE_DOCS = "https://renode.readthedocs.io/en/latest/introduction/installing.html"

INSTALL_ROOT = Path.home() / ".local" / "share" / "gar" / "renode"
BIN_DIR = Path.home() / ".local" / "bin"
LAUNCHER = BIN_DIR / "renode"


class RenodeMcuEnvironment(DevEnvironment):
    provider_id = "renode_mcu"
    display_name = "Renode (MCU/ベアメタル)"
    description = (
        "Cortex-M / RISC-V などの MCU ファームを命令セットエミュレータで仮想実行します"
        "（未改変バイナリを sim と実機で共有。ランタイム統合は今後対応）"
    )
    display_order = 10
    required_commands = ("renode",)

    @classmethod
    def install_hint(cls, missing: list[str]) -> str:
        return (
            "Renode が見つかりません。\n"
            "Linux / WSL2 では gar が user-local の portable build を導入できます。\n"
            "手動で入れる場合は公式リリース/ドキュメントを参照してください:\n"
            f"  - releases: {RENODE_RELEASES_PAGE}\n"
            f"  - docs:     {RENODE_DOCS}\n"
            f"導入後は {BIN_DIR} を PATH に含めてください。"
        )

    @classmethod
    def install_dependencies(cls, missing: list[str]) -> int:
        if platform.system() != "Linux":
            print(cls.install_hint(missing))
            print(
                "自動インストールは Linux / WSL2 のみ対応です。"
                "現行アーキテクチャ方針では simulation は WSL/EC2 上で動かします。"
            )
            return 1

        arch = _host_arch()
        if arch is None:
            print(cls.install_hint(missing))
            print(f"未対応の CPU アーキテクチャです: {platform.machine()}")
            return 1

        try:
            release = _fetch_latest_release()
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(cls.install_hint(missing))
            print(f"最新リリース情報の取得に失敗しました: {exc}")
            return 1

        asset = _select_portable_asset(release.get("assets", []), arch)
        if asset is None:
            print(cls.install_hint(missing))
            print(
                f"このホスト ({arch}) 向けの portable build が見つかりませんでした。\n"
                "x86_64 の WSL2 / EC2 上での導入を推奨します。"
            )
            return 1

        return _install_portable(asset, release.get("tag_name", "latest"))

    # ------------------------------------------------------------------
    # ランタイム系: Renode ターゲットの統合は今後対応。現時点は安全に降格する。
    # （selection しても gar sim env が NotImplementedError で落ちないようにする）
    # ------------------------------------------------------------------
    @classmethod
    def run_remote(
        cls,
        target: str,
        command: str,
        *,
        capture_output: bool = False,
        text: bool = True,
        check: bool = False,
    ):
        message = _runtime_unwired_message()
        if not capture_output:
            print(message, file=sys.stderr)
        result = subprocess.CompletedProcess(
            args=["renode_mcu", "run_remote", target],
            returncode=1,
            stdout="" if text else b"",
            stderr=message if text else message.encode(),
        )
        if check:
            raise subprocess.CalledProcessError(
                result.returncode,
                result.args,
                output=result.stdout,
                stderr=result.stderr,
            )
        return result

    @classmethod
    def push_file(cls, target: str, src, dest) -> int:
        print(_runtime_unwired_message(), file=sys.stderr)
        return 1

    @classmethod
    def pull_file(cls, target: str, src, dest) -> int:
        print(_runtime_unwired_message(), file=sys.stderr)
        return 1

    @classmethod
    def start_port_forward(cls, target: str) -> int:
        print(_runtime_unwired_message(), file=sys.stderr)
        return 1

    @classmethod
    def stop_port_forward(cls, target: str) -> int:
        print(_runtime_unwired_message(), file=sys.stderr)
        return 1

    @classmethod
    def status_port_forward(cls, target: str) -> int:
        print(_runtime_unwired_message(), file=sys.stderr)
        return 1

    @classmethod
    def interactive_shell_script(cls, target: str) -> str:
        return f"""#!/usr/bin/env bash
set -euo pipefail

cat >&2 <<'EOF'
{_runtime_unwired_message()}
EOF
exit 1
"""


def _runtime_unwired_message() -> str:
    return (
        "Renode (renode_mcu) provider の gar sim env ランタイム統合は未配線です。\n"
        "現時点では Renode の導入/検証のみ対応します。"
        "Linux runtime 操作には ssh_remote provider を使ってください。"
    )


def _host_arch() -> str | None:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    if machine in ("aarch64", "arm64"):
        return "aarch64"
    return None


def _fetch_latest_release() -> dict:
    request = urllib.request.Request(
        RENODE_RELEASES_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "gar-setup",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _select_portable_asset(assets: list[dict], arch: str) -> dict | None:
    """ホスト arch 向けの Linux portable tarball を substring 一致で選ぶ。

    asset 名の正確な命名はリリースごとに変わりうるため、トークン一致で
    最も妥当な候補を選び、固定 URL の推測を避ける。
    """
    candidates = [
        asset
        for asset in assets
        if isinstance(asset.get("name"), str)
        and asset.get("browser_download_url")
        and _is_linux_portable(asset["name"])
    ]
    if not candidates:
        return None

    arch_tokens = ("x86_64", "amd64") if arch == "x86_64" else ("arm64", "aarch64")

    # arch 明示のあるものを優先。なければ x86_64 ホストに限り arch 非明記も許容。
    arch_specific = [a for a in candidates if _name_has_token(a["name"], arch_tokens)]
    if arch_specific:
        return _prefer_dotnet(arch_specific)

    if arch == "x86_64":
        generic = [
            a
            for a in candidates
            if not _name_has_token(a["name"], ("arm64", "aarch64"))
        ]
        if generic:
            return _prefer_dotnet(generic)

    return None


def _is_linux_portable(name: str) -> bool:
    lower = name.lower()
    return (
        "linux" in lower
        and "portable" in lower
        and (lower.endswith(".tar.gz") or lower.endswith(".tar.xz"))
    )


def _name_has_token(name: str, tokens: tuple[str, ...]) -> bool:
    lower = name.lower()
    return any(token in lower for token in tokens)


def _prefer_dotnet(assets: list[dict]) -> dict:
    for asset in assets:
        if "dotnet" in asset["name"].lower():
            return asset
    return assets[0]


def _install_portable(asset: dict, tag: str) -> int:
    name = asset["name"]
    url = asset["browser_download_url"]
    print(f"Renode portable build を導入します: {name} ({tag})")

    with tempfile.TemporaryDirectory(prefix="gar-renode-") as tmp:
        tarball = Path(tmp) / name
        try:
            _download(url, tarball)
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"ダウンロードに失敗しました: {exc}")
            return 1

        extract_dir = Path(tmp) / "extracted"
        extract_dir.mkdir()
        try:
            _safe_extract(tarball, extract_dir)
        except (tarfile.TarError, ValueError) as exc:
            print(f"展開に失敗しました: {exc}")
            return 1

        launcher = _find_renode_launcher(extract_dir)
        if launcher is None:
            print("展開結果から renode 起動スクリプトを特定できませんでした。")
            return 1

        if INSTALL_ROOT.exists():
            shutil.rmtree(INSTALL_ROOT)
        INSTALL_ROOT.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(launcher.parent), str(INSTALL_ROOT))

    installed_launcher = INSTALL_ROOT / "renode"
    if not installed_launcher.exists():
        # tarball 内のスクリプト名が renode でない場合に備えて探索
        found = _find_renode_launcher(INSTALL_ROOT)
        if found is None:
            print("導入先に renode 起動スクリプトが見つかりませんでした。")
            return 1
        installed_launcher = found

    installed_launcher.chmod(0o755)
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    if LAUNCHER.exists() or LAUNCHER.is_symlink():
        LAUNCHER.unlink()
    LAUNCHER.symlink_to(installed_launcher)

    print(f"導入完了: {LAUNCHER} -> {installed_launcher}")
    if shutil.which("renode") is None:
        print(
            f"注意: PATH に {BIN_DIR} が含まれていません。"
            "シェル設定に追加してから `gar setup` を再実行してください。\n"
            f'  export PATH="{BIN_DIR}:$PATH"'
        )
        return 1
    return 0


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "gar-setup"})
    with urllib.request.urlopen(request, timeout=300) as response, dest.open("wb") as out:  # noqa: S310
        shutil.copyfileobj(response, out)


def _safe_extract(tarball: Path, dest: Path) -> None:
    dest_resolved = dest.resolve()
    with tarfile.open(tarball, "r:*") as tar:
        for member in tar.getmembers():
            target = (dest / member.name).resolve()
            if not str(target).startswith(str(dest_resolved)):
                raise ValueError(f"path traversal を検出しました: {member.name}")
        tar.extractall(dest)  # noqa: S202


def _find_renode_launcher(root: Path) -> Path | None:
    direct = root / "renode"
    if direct.is_file():
        return direct
    matches = sorted(root.rglob("renode"))
    for match in matches:
        if match.is_file():
            return match
    return None
