"""Wokwi simulation environment provider."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from scripts.gar_lib.environments.base import CommandStatus, DevEnvironment


class WokwiEnvironment(DevEnvironment):
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
        result = cls.run_subprocess(["sh", "-c", "curl -L https://wokwi.com/ci/install.sh | sh"])
        if result == 0:
            _refresh_wokwi_path()
        return result

    @classmethod
    def list_instances(cls) -> int:
        print("target: local Wokwi project directory / firmware artifact")
        print("runtime: Wokwi CI cloud simulation (uses WOKWI_CLI_TOKEN)")
        print("default project: GaplessAgentRuntime/.gar/wokwi/m5stackc")
        return 0

    @classmethod
    def shell(cls, target: str | None = None) -> int:
        del target
        print("Wokwi simulation provider is configured.")
        print("Run: gar sim env start --no-port-forward")
        return 0

    @classmethod
    def start_port_forward(cls, target: str) -> int:
        return 0

    @classmethod
    def stop_port_forward(cls, target: str) -> int:
        return 0

    @classmethod
    def status_port_forward(cls, target: str) -> int:
        return 0

    @classmethod
    def interactive_shell_script(cls, target: str) -> str:
        return """#!/usr/bin/env bash
set -euo pipefail

echo "Wokwi simulation provider is configured."
echo "Runtime: Wokwi CI cloud simulation via local wokwi-cli."
echo "Project: ${GAR_WOKWI_PROJECT_DIR:-$PWD/.gar/wokwi/m5stackc}"
echo "Run: gar sim env start --no-port-forward"
"""


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
