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
import os
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
TEST_VENV = Path.home() / ".local" / "share" / "gar" / "renode-test-venv"
BIN_DIR = Path.home() / ".local" / "bin"
LAUNCHER = BIN_DIR / "renode"
TEST_LAUNCHER = BIN_DIR / "renode-test"


class RenodeMcuEnvironment(DevEnvironment):
    provider_id = "renode_mcu"
    display_name = "Renode (MCU/ベアメタル)"
    description = (
        "Cortex-M / RISC-V などの MCU ファームを命令セットエミュレータで仮想実行します"
        "（未改変バイナリを sim と実機で共有。ランタイム統合は今後対応）"
    )
    display_order = 10
    required_commands = ("renode", "renode-test")

    @classmethod
    def dependency_status(cls):
        renode_path = shutil.which("renode")
        renode_test_path = shutil.which("renode-test")
        if renode_test_path and not _renode_test_works(renode_test_path):
            renode_test_path = None
        from scripts.gar_lib.environments.base import CommandStatus

        return [
            CommandStatus(name="renode", path=renode_path),
            CommandStatus(name="renode-test", path=renode_test_path),
        ]

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

        if "renode" not in missing and INSTALL_ROOT.exists():
            return _finish_existing_install()

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

        installed_launcher = _find_renode_launcher(INSTALL_ROOT)
        if installed_launcher is None:
            print("導入先に renode 起動スクリプトが見つかりませんでした。")
            return 1

    return _finish_launcher_install(installed_launcher)


def _finish_existing_install() -> int:
    installed_launcher = _find_renode_launcher(INSTALL_ROOT)
    if installed_launcher is None:
        print("既存の Renode 導入先から renode 起動スクリプトを特定できませんでした。")
        return 1
    return _finish_launcher_install(installed_launcher)


def _finish_launcher_install(installed_launcher: Path) -> int:
    installed_launcher.chmod(0o755)
    installed_test_launcher = _find_renode_test_launcher(INSTALL_ROOT)
    if installed_test_launcher is not None:
        installed_test_launcher.chmod(0o755)

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    _write_launcher(LAUNCHER, installed_launcher, set_globalization_invariant=True)
    if installed_test_launcher is not None:
        if _install_renode_test_dependencies() != 0:
            return 1
        _write_launcher(TEST_LAUNCHER, installed_test_launcher, test_venv=TEST_VENV)

    print(f"導入完了: {LAUNCHER} -> {installed_launcher}")
    if installed_test_launcher is not None:
        print(f"導入完了: {TEST_LAUNCHER} -> {installed_test_launcher}")
    else:
        print("注意: renode-test 起動スクリプトは tarball 内に見つかりませんでした。")

    _ensure_bin_dir_on_path()
    _ensure_bashrc_path()

    if shutil.which("renode") is None or shutil.which("renode-test") is None:
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


def _find_renode_test_launcher(root: Path) -> Path | None:
    direct = root / "renode-test"
    if direct.is_file():
        return direct
    matches = sorted(root.rglob("renode-test"))
    for match in matches:
        if match.is_file():
            return match
    return None


def _write_launcher(
    path: Path,
    target: Path,
    *,
    set_globalization_invariant: bool = True,
    test_venv: Path | None = None,
) -> None:
    if path.exists() or path.is_symlink():
        path.unlink()

    exports = ""
    if set_globalization_invariant:
        # Portable .NET build can fail on minimal WSL images without libicu.
        # Users may still override this by exporting the variable themselves.
        exports = 'export DOTNET_SYSTEM_GLOBALIZATION_INVARIANT="${DOTNET_SYSTEM_GLOBALIZATION_INVARIANT:-1}"\n'
    if test_venv is not None:
        exports += f'source "{test_venv / "bin" / "activate"}"\n'

    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"{exports}"
        f'exec "{target}" "$@"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)


def _ensure_bin_dir_on_path() -> None:
    path_entries = os.environ.get("PATH", "").split(":")
    bin_dir = str(BIN_DIR)
    if bin_dir not in path_entries:
        os.environ["PATH"] = f"{bin_dir}:{os.environ.get('PATH', '')}"


def _ensure_bashrc_path() -> None:
    bashrc = Path.home() / ".bashrc"
    line = 'export PATH="$HOME/.local/bin:$PATH"'
    try:
        current = bashrc.read_text(encoding="utf-8") if bashrc.exists() else ""
    except OSError:
        return
    if line in current:
        return
    suffix = "" if not current or current.endswith("\n") else "\n"
    try:
        bashrc.write_text(current + suffix + line + "\n", encoding="utf-8")
    except OSError:
        return


def _renode_test_works(path: str) -> bool:
    env = os.environ.copy()
    env.setdefault("DOTNET_SYSTEM_GLOBALIZATION_INVARIANT", "1")
    result = subprocess.run(
        [path, "--help"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return result.returncode == 0


def _install_renode_test_dependencies() -> int:
    TEST_VENV.parent.mkdir(parents=True, exist_ok=True)
    if not (TEST_VENV / "bin" / "python").exists():
        print(f"renode-test 用 Python venv を作成します: {TEST_VENV}")
        result = subprocess.run(
            [sys.executable, "-m", "venv", str(TEST_VENV)],
            check=False,
        )
        if result.returncode != 0:
            print(
                "renode-test 用 venv の作成に失敗しました。"
                "python3-venv を導入してから `gar setup` を再実行してください。"
            )
            return result.returncode

    pip = TEST_VENV / "bin" / "pip"
    packages = [
        "robotframework==6.1",
        "robotframework-retryfailed==0.2.0",
        "psutil>=6.1",
        "pyyaml>=6.0",
        "telnetlib3==2.0.*",
        "construct==2.10.68",
        "pyelftools==0.30",
    ]
    print("renode-test 用 Python 依存関係を導入します。")
    return subprocess.run(
        [str(pip), "install", "--upgrade", *packages],
        check=False,
    ).returncode
