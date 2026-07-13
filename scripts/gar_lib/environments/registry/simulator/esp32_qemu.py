"""ESP32 firmware QEMU runner provider.

GAR の tool list から、gar-tools 側に置いた ESP32 firmware runner を呼ぶ。
Renode の .repl/.resc はボード定義を育てる場所として残しつつ、今日
`firmware.bin` を起動する実用パスは Espressif QEMU に寄せる。
"""

from __future__ import annotations

from scripts.gar_lib.environments.base import EnvironmentSetupOption


class Esp32QemuFirmwareEnvironment(EnvironmentSetupOption):
    provider_id = "esp32_qemu_firmware"
    display_name = "ESP32 QEMU Firmware"
    description = (
        "bootloader/partition/firmware artifact を flash image にまとめ、"
        "Espressif QEMU で ESP32 firmware を起動します（runtime操作は現在stub）"
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
