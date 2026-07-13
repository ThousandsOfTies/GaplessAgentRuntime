"""Wokwi simulation environment provider."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from scripts.gar_lib.environments.base import CommandStatus, EnvironmentSetupOption


class WokwiEnvironment(EnvironmentSetupOption):
    provider_id = "wokwi"
    display_name = "Wokwi"
    description = "ローカルCLIから Wokwi CI のクラウドESP32/M5StackCシミュレーションを実行します"
    display_order = 16
    required_commands = ("wokwi-cli",)

    @classmethod
    def dependency_status(cls) -> list[CommandStatus]:
        return [CommandStatus(name="wokwi-cli", path=_find_wokwi_cli())]

    @classmethod
    def install_hint(cls, missing: list[str]) -> str:
        del missing
        return (
            "Install Wokwi CLI: curl -L https://wokwi.com/ci/install.sh | sh\n"
            "インストール後に見つからない場合は `source ~/.bashrc` を実行してください。"
        )

    @classmethod
    def install_dependencies(cls, missing: list[str]) -> int:
        if "wokwi-cli" not in missing:
            print(cls.install_hint(missing))
            return 1

        if shutil.which("curl") is None or shutil.which("sh") is None:
            print(cls.install_hint(missing))
            return 1

        print("Wokwi CLI をインストールします。")
        print("インストールスクリプト: https://wokwi.com/ci/install.sh")
        result = cls.run_install_command(["sh", "-c", "curl -L https://wokwi.com/ci/install.sh | sh"])
        if result == 0:
            _refresh_wokwi_path()
        return result


def _find_wokwi_cli() -> str | None:
    found = shutil.which("wokwi-cli")
    if found:
        return found

    for path in _wokwi_candidate_paths():
        if path.exists() and os.access(path, os.X_OK):
            return str(path)

    return None


def _wokwi_candidate_paths() -> list[Path]:
    home = Path.home()
    return [
        home / "bin" / "wokwi-cli",
        home / ".wokwi" / "bin" / "wokwi-cli",
    ]


def _refresh_wokwi_path() -> None:
    current_parts = os.environ.get("PATH", "").split(os.pathsep)
    extra_dirs = []
    for path in _wokwi_candidate_paths():
        parent = str(path.parent)
        if path.exists() and parent not in current_parts:
            extra_dirs.append(parent)

    if extra_dirs:
        os.environ["PATH"] = os.pathsep.join([*extra_dirs, *current_parts])
