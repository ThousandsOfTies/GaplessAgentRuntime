import contextlib
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.gar_lib.artifacts.manifest import fetch_codespace_artifacts
from scripts.gar_lib.target.esptool import normalize_esp32_serial_port, run_esp32_flash_command


class GarTargetCliTest(unittest.TestCase):
    def test_target_fetch_copies_manifest_sources_from_codespace(self) -> None:
        manifest = {
            "name": "sensor-demo",
            "deploy": {
                "app": {"files": [{"src": "files/sensor_demo", "dest": "/home/user/sensor_demo", "mode": "0755"}]},
                "sim_env": {
                    "files": [
                        {"src": "files/cuse_i2c", "dest": "~/cuse_i2c", "mode": "0755"},
                        {"src": "files/web-bridge", "dest": "~/web-bridge"},
                    ]
                },
            },
        }

        def fake_cp(
            codespace: str,
            remote_path: str,
            local_path: Path,
            *,
            recursive: bool = False,
        ) -> subprocess.CompletedProcess:
            self.assertEqual("codespace-test", codespace)
            if remote_path.endswith("/artifact.json"):
                local_path.write_text(json.dumps(manifest), encoding="utf-8")
                return subprocess.CompletedProcess(args=[], returncode=0)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            if remote_path.endswith("/files/web-bridge"):
                local_path.mkdir(parents=True, exist_ok=True)
                (local_path / "bridge.py").write_text("", encoding="utf-8")
            else:
                local_path.write_text("", encoding="utf-8")
            self.assertTrue(recursive)
            return subprocess.CompletedProcess(args=[], returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                mock.patch("scripts.gar_lib.artifacts.manifest.select_codespace", return_value="codespace-test"),
                mock.patch("scripts.gar_lib.artifacts.manifest.gh_codespace_cp", side_effect=fake_cp) as cp,
            ):
                result = fetch_codespace_artifacts(root, remote_root="/workspaces/out")

            written_manifest = json.loads((root / "artifact.json").read_text(encoding="utf-8"))

        self.assertEqual(0, result)
        self.assertEqual(manifest, written_manifest)
        self.assertEqual(4, cp.call_count)

    def test_esp32_serial_port_maps_windows_com_to_wsl_tty(self) -> None:
        for platform_name, expected in (("posix", "/dev/ttyS3"), ("nt", "COM3")):
            with (
                self.subTest(platform=platform_name),
                mock.patch("scripts.gar_lib.target.esptool.os", SimpleNamespace(name=platform_name)),
            ):
                self.assertEqual(expected, normalize_esp32_serial_port("COM3"))

    def test_esp32_serial_port_uses_environment_fallback(self) -> None:
        with mock.patch.dict(os.environ, {"GAR_ESP32_PORT": "COM4"}):
            self.assertEqual("COM4" if os.name == "nt" else "/dev/ttyS4", normalize_esp32_serial_port(None))

    def test_esp32_flash_verifies_and_invokes_esptool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for filename in (
                "bootloader.bin",
                "partitions.bin",
                "boot_app0.bin",
                "firmware.bin",
            ):
                (root / filename).write_bytes(f"{filename}\n".encode())
            sums = []
            for filename in (
                "boot_app0.bin",
                "bootloader.bin",
                "firmware.bin",
                "partitions.bin",
            ):
                digest = hashlib.sha256((root / filename).read_bytes()).hexdigest()
                sums.append(f"{digest}  {filename}\n")
            (root / "SHA256SUMS").write_text("".join(sums), encoding="utf-8")

            completed = mock.Mock(returncode=0)
            with (
                mock.patch(
                    "scripts.gar_lib.target.esptool.ensure_esptool_python",
                    return_value=Path("/opt/gar-esptool/bin/python"),
                ),
                mock.patch(
                    "scripts.gar_lib.target.esptool.esp32_serial_port_access_error",
                    return_value=None,
                ),
                mock.patch(
                    "scripts.gar_lib.target.esptool.subprocess.run",
                    return_value=completed,
                ) as run,
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = run_esp32_flash_command(
                        artifact_dir=str(root),
                        port="COM3",
                        baud=460800,
                    )

        self.assertEqual(0, result)
        args = run.call_args.args[0]
        self.assertEqual(str(Path("/opt/gar-esptool/bin/python")), args[0])
        self.assertIn("--port", args)
        self.assertEqual("COM3" if os.name == "nt" else "/dev/ttyS3", args[args.index("--port") + 1])
        self.assertIn("--baud", args)
        self.assertEqual("460800", args[args.index("--baud") + 1])
        self.assertIn("0x10000", args)
        self.assertTrue(str(root / "firmware.bin") in args)
        self.assertIn("write-flash", args)
        self.assertIn("Flash complete.", output.getvalue())

    def test_esp32_flash_stops_before_esptool_when_serial_port_is_inaccessible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for filename in (
                "bootloader.bin",
                "partitions.bin",
                "boot_app0.bin",
                "firmware.bin",
            ):
                (root / filename).write_bytes(b"ok")

            with (
                mock.patch(
                    "scripts.gar_lib.target.esptool.esp32_serial_port_access_error",
                    return_value="serial port is not readable/writable by current user: /dev/ttyS3",
                ),
                mock.patch("scripts.gar_lib.target.esptool.ensure_esptool_python") as ensure_esptool,
            ):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    result = run_esp32_flash_command(
                        artifact_dir=str(root),
                        port="COM3",
                        verify=False,
                    )

        self.assertEqual(1, result)
        ensure_esptool.assert_not_called()
        self.assertIn("not readable/writable", err.getvalue())

    def test_esp32_flash_hints_usbipd_when_wsl_com_flash_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for filename in (
                "bootloader.bin",
                "partitions.bin",
                "boot_app0.bin",
                "firmware.bin",
            ):
                (root / filename).write_bytes(b"ok")

            completed = mock.Mock(returncode=2)
            with (
                mock.patch("scripts.gar_lib.target.esptool.os", SimpleNamespace(name="posix")),
                mock.patch(
                    "scripts.gar_lib.target.esptool.ensure_esptool_python",
                    return_value=Path("/opt/gar-esptool/bin/python"),
                ),
                mock.patch(
                    "scripts.gar_lib.target.esptool.esp32_serial_port_access_error",
                    return_value=None,
                ),
                mock.patch(
                    "scripts.gar_lib.target.esptool.subprocess.run",
                    return_value=completed,
                ),
            ):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    result = run_esp32_flash_command(
                        artifact_dir=str(root),
                        port="COM3",
                        verify=False,
                    )

        self.assertEqual(2, result)
        self.assertIn("usbipd", err.getvalue())
        self.assertIn("/dev/ttyUSB0", err.getvalue())


if __name__ == "__main__":
    unittest.main()
