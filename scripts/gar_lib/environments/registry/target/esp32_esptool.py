"""ESP32 esptool setup option."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from scripts.gar_lib.config import PROJECT_ROOT
from scripts.gar_lib.environments.base import CommandStatus, EnvironmentSetupOption


class Esp32EsptoolEnvironment(EnvironmentSetupOption):
    provider_id = "esp32_esptool"
    display_name = "ESP32 esptool"
    description = "esptool で ESP32/M5Stack firmware を USBシリアル経由で実機へ書き込みます"
    display_order = 20

    required_commands = ("esptool",)

    @classmethod
    def dependency_status(cls) -> list[CommandStatus]:
        return [CommandStatus(name="esptool", path=_find_tool("esptool"))]

    @classmethod
    def install_hint(cls, missing: list[str]) -> str:
        commands = ", ".join(missing)
        return (
            f"不足: {commands}\n"
            "GAR の .venv に ESP32 書き込みツール esptool をインストールします。\n"
            "MicroPython REPL/ファイル転送も使う場合は mpremote も追加できます。\n"
            "手動で行う場合: .venv/bin/python -m pip install esptool"
        )

    @classmethod
    def install_dependencies(cls, missing: list[str]) -> int:
        if "esptool" not in missing:
            print(cls.install_hint(missing))
            return 1

        python = _install_python()
        if python is None:
            print(cls.install_hint(missing))
            return 1

        print("ESP32 firmware 書き込みツール esptool を GAR の .venv にインストールします。")
        result = cls.run_install_command([str(python), "-m", "pip", "install", "esptool"])
        if result == 0:
            _refresh_tool_path()
        return result


def _find_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found

    for path in _tool_candidate_paths(name):
        if path.exists() and os.access(path, os.X_OK):
            return str(path)

    return None


def _tool_candidate_paths(name: str) -> list[Path]:
    return [
        PROJECT_ROOT / ".venv" / "bin" / name,
        Path.home() / ".local" / "bin" / name,
    ]


def _install_python() -> Path | None:
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return venv_python
    return Path(sys.executable) if sys.executable else None


def _refresh_tool_path() -> None:
    current_parts = os.environ.get("PATH", "").split(os.pathsep)
    extra_dirs = []
    for path in _tool_candidate_paths("esptool"):
        parent = str(path.parent)
        if path.exists() and parent not in current_parts:
            extra_dirs.append(parent)

    if extra_dirs:
        os.environ["PATH"] = os.pathsep.join([*extra_dirs, *current_parts])
