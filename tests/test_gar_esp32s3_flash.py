from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.gar_lib.build.local import LocalBuildEnvironment
from scripts.gar_lib.target.esp32_firmware import FLASH_LAYOUT, flash_profile
from scripts.gar_lib.target.esptool import run_esp32_flash_command


class Esp32S3FlashTest(unittest.TestCase):
    def bundle(self, root):
        header = bytearray(24)
        header[0] = 0xE9
        header[12] = 9
        for _, name in FLASH_LAYOUT:
            (root / name).write_bytes(header)
        (root / "flash.json").write_text(json.dumps({"schema_version": 1, "chip": "esp32s3"}))

    def test_s3_uses_chip_guard_and_zero_bootloader_offset(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.bundle(root)
            with (
                mock.patch("scripts.gar_lib.target.esptool.ensure_esptool_python", return_value=Path(sys.executable)),
                mock.patch("scripts.gar_lib.target.esptool.esp32_serial_port_access_error", return_value=None),
                mock.patch("scripts.gar_lib.target.esptool.run_displayed", return_value=mock.Mock(returncode=0)) as run,
            ):
                self.assertEqual(0, run_esp32_flash_command(artifact_dir=str(root), port="COM10", verify=False))
            args = run.call_args.args[0]
            self.assertEqual("esp32s3", args[args.index("--chip") + 1])
            self.assertEqual(str(root.resolve() / "bootloader.bin"), args[args.index("0x0") + 1])
            self.assertNotIn("0x1000", args)

    def test_wrong_chip_image_and_unknown_profile_fail_before_opening_port(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.bundle(root)
            (root / "firmware.bin").write_bytes(b"wrong-chip")
            with mock.patch("scripts.gar_lib.target.esptool.run_displayed") as run:
                self.assertEqual(1, run_esp32_flash_command(artifact_dir=str(root), port="COM10"))
                run.assert_not_called()
            (root / "flash.json").write_text('{"schema_version":1,"chip":"other"}')
            with self.assertRaises(ValueError):
                flash_profile(root)

    def test_legacy_layout_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(("esp32", FLASH_LAYOUT), flash_profile(Path(temporary)))

    def test_python_native_hook_uses_current_interpreter(self):
        with tempfile.TemporaryDirectory() as temporary:
            shell = Path(temporary) / "product-target-build.sh"
            python = shell.with_suffix(".py")
            python.write_text("print('build')")
            self.assertEqual([sys.executable, str(python)], LocalBuildEnvironment._command(shell))


if __name__ == "__main__":
    unittest.main()
