import contextlib
import io
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.gar_lib.cli import main
from scripts.gar_lib.console import configure_output

ROOT = Path(__file__).resolve().parents[1]


class ConsoleOutputTests(unittest.TestCase):
    def test_help_and_errors_survive_redirected_windows_code_pages(self) -> None:
        for argv in (["--help"], ["target", "--help"], ["--unknown-option"]):
            with self.subTest(argv=argv):
                output = io.BytesIO()
                errors = io.BytesIO()
                with (
                    io.TextIOWrapper(output, encoding="cp1252") as stdout,
                    io.TextIOWrapper(errors, encoding="cp1252") as stderr,
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                    patch("scripts.gar_lib.console.sys.platform", "win32"),
                ):
                    if argv == ["--unknown-option"]:
                        with self.assertRaises(SystemExit) as exit_code:
                            main(argv)
                        self.assertEqual(2, exit_code.exception.code)
                    else:
                        self.assertEqual(0, main(argv))
                    stdout.flush()
                    stderr.flush()
                    message = output.getvalue().decode("utf-8") + errors.getvalue().decode("utf-8")
                    self.assertIn("usage: gar", message)
                    self.assertEqual("utf-8", stdout.encoding)
                    self.assertEqual("utf-8", stderr.encoding)

    def test_captured_streams_without_reconfigure_are_supported(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with patch("scripts.gar_lib.console.sys.platform", "win32"):
                self.assertEqual(0, main(["--help"]))

    def test_non_windows_stream_encoding_is_preserved(self) -> None:
        with io.TextIOWrapper(io.BytesIO(), encoding="latin-1") as stdout:
            with contextlib.redirect_stdout(stdout), patch("scripts.gar_lib.console.sys.platform", "linux"):
                configure_output()
                self.assertEqual("latin-1", stdout.encoding)

    @unittest.skipUnless(sys.platform == "win32", "Windows entry points")
    def test_windows_entry_points_with_legacy_redirected_output(self) -> None:
        environment = dict(
            os.environ, PYTHONIOENCODING="cp1252", PYTHONDONTWRITEBYTECODE="1", GAR_VENV=str(ROOT / ".venv")
        )
        for arguments, expected_code in (
            (["-m", "scripts.gar_lib", "--help"], 0),
            (["-m", "scripts.gar_lib", "target", "--help"], 0),
            (["scripts/gar", "--help"], 0),
            (["scripts/setup", "--unknown-option"], 2),
        ):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, *arguments], cwd=ROOT, env=environment, capture_output=True, check=False
                )
                self.assertEqual(expected_code, result.returncode, result.stderr.decode("utf-8"))
                self.assertIn("usage:", (result.stdout + result.stderr).decode("utf-8"))
                self.assertNotIn(b"UnicodeEncodeError", result.stderr)
