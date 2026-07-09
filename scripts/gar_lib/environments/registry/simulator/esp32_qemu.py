"""ESP32 firmware QEMU runner provider.

GAR の tool list から、gar-tools 側に置いた ESP32 firmware runner を呼ぶ。
Renode の .repl/.resc はボード定義を育てる場所として残しつつ、今日
`firmware.bin` を起動する実用パスは Espressif QEMU に寄せる。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from scripts.gar_lib.environments.base import DevEnvironment

DEFAULT_ARTIFACT = (
    Path.home()
    / "Yurufuwa"
    / "gar-vibe-ui"
    / "vibe-remote"
    / "m5stickc-client"
    / "artifacts"
    / "20260620-070805-m5stickc-plus2-vibe-min"
)
DEFAULT_TOOLS = Path.home() / "Yurufuwa" / "gar-tools" / "targets" / "esp32"


class Esp32QemuFirmwareEnvironment(DevEnvironment):
    provider_id = "esp32_qemu_firmware"
    display_name = "ESP32 QEMU Firmware"
    description = (
        "bootloader/partition/firmware artifact を flash image にまとめ、"
        "Espressif QEMU で ESP32 firmware を起動します"
    )
    display_order = 15
    required_commands = ("qemu-system-xtensa",)

    @classmethod
    def install_hint(cls, missing: list[str]) -> str:
        commands = ", ".join(missing)
        return (
            f"不足: {commands}\n"
            "ESP-IDF の Espressif QEMU を入れてください:\n"
            '  python "$IDF_PATH/tools/idf_tools.py" install qemu-xtensa\n'
            '  . "$IDF_PATH/export.sh"\n'
            "詳細: https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-guides/tools/qemu.html"
        )

    @classmethod
    def list_instances(cls) -> int:
        print(f"default artifact: {_artifact_path(None)}")
        print(f"flash builder:    {_flash_builder()}")
        print(f"qemu runner:      {_qemu_runner()}")
        print("run:")
        print("  gar setup でこの provider を選び、artifact directory を target にして shell を開く")
        return 0

    @classmethod
    def shell(cls, target: str | None = None) -> int:
        artifact_or_flash = _artifact_path(target)
        flash_image = _flash_image_path(artifact_or_flash)

        if artifact_or_flash.is_dir():
            builder = _flash_builder()
            if not builder.exists():
                print(f"flash image builder not found: {builder}")
                return 1
            build = subprocess.run(
                [
                    str(builder),
                    "--artifact",
                    str(artifact_or_flash),
                    "--output",
                    str(flash_image),
                ],
                check=False,
            )
            if build.returncode != 0:
                return build.returncode
        elif artifact_or_flash.is_file():
            flash_image = artifact_or_flash
        else:
            print(f"artifact directory or flash image not found: {artifact_or_flash}")
            return 1

        runner = _qemu_runner()
        if not runner.exists():
            print(f"QEMU runner not found: {runner}")
            return 1
        return subprocess.run([str(runner), str(flash_image)], check=False).returncode

    @classmethod
    def interactive_shell_script(cls, target: str) -> str:
        artifact_or_flash = _artifact_path(target)
        flash_image = _flash_image_path(artifact_or_flash)
        return f"""#!/usr/bin/env bash
set -euo pipefail

if [ -d "{artifact_or_flash}" ]; then
  {str(_flash_builder())} --artifact "{artifact_or_flash}" --output "{flash_image}"
fi

exec {str(_qemu_runner())} "{flash_image}"
"""


def _tools_root() -> Path:
    return Path(os.environ.get("GAR_ESP32_TOOLS", str(DEFAULT_TOOLS))).expanduser()


def _flash_builder() -> Path:
    return _tools_root() / "qemu" / "bin" / "gar-esp32-flash-image"


def _qemu_runner() -> Path:
    return _tools_root() / "qemu" / "bin" / "gar-esp32-qemu-run"


def _artifact_path(target: str | None) -> Path:
    configured = target or os.environ.get("GAR_ESP32_ARTIFACT") or str(DEFAULT_ARTIFACT)
    return Path(configured).expanduser().resolve()


def _flash_image_path(artifact_or_flash: Path) -> Path:
    if artifact_or_flash.is_file():
        return artifact_or_flash
    return Path(os.environ.get("GAR_ESP32_FLASH", "/tmp/gar-esp32-flash.bin")).expanduser()
