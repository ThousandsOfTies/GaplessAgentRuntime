from __future__ import annotations

import io
import subprocess
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest import mock

from scripts.gar_lib.bootstrap import VENV, VENV_PYTHON, relaunch_in_venv
from scripts.gar_lib.launcher_setup import (
    COMPLETION_BLOCK_END,
    COMPLETION_BLOCK_START,
    offer_scripts_path_registration,
    offer_shell_completion_registration,
)


class TtyInput(io.StringIO):
    def isatty(self) -> bool:
        return True


class GarLauncherSetupTest(unittest.TestCase):
    def test_current_path_duplicate_skips_without_prompt(self) -> None:
        scripts = mock.Mock(spec=Path)
        scripts.resolve.return_value = PurePosixPath("/tmp/product/scripts")
        output = io.StringIO()
        result = offer_scripts_path_registration(
            scripts,
            stdin=TtyInput("\n"),
            stdout=output,
            environ={"PATH": f'"{scripts.resolve()}/"'},
            platform="posix",
        )

        self.assertEqual(0, result)
        self.assertIn("現在のPATHでgarを使用できます", output.getvalue())
        self.assertNotIn("[Y/n]", output.getvalue())

    def test_windows_persistent_path_duplicate_skips_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scripts = Path(temporary_directory) / "scripts"
            scripts.mkdir()
            output = io.StringIO()
            with (
                mock.patch(
                    "scripts.gar_lib.launcher_setup._read_windows_user_path",
                    return_value=(str(scripts.resolve()).upper(), 2),
                ),
                mock.patch("scripts.gar_lib.launcher_setup._write_windows_user_path") as write_path,
            ):
                result = offer_scripts_path_registration(
                    scripts,
                    stdin=TtyInput("\n"),
                    stdout=output,
                    environ={"PATH": ""},
                    platform="nt",
                )

        self.assertEqual(0, result)
        write_path.assert_not_called()
        self.assertIn("ユーザーPATHには登録済みですが、現在のterminalには未反映", output.getvalue())
        self.assertIn("terminal hostを完全終了", output.getvalue())
        self.assertIn("「ファイル」→「終了」", output.getvalue())
        self.assertNotIn("[Y/n]", output.getvalue())

    def test_windows_default_yes_appends_user_path_and_broadcasts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scripts = Path(temporary_directory) / "scripts"
            scripts.mkdir()
            output = io.StringIO()
            with (
                mock.patch(
                    "scripts.gar_lib.launcher_setup._read_windows_user_path",
                    return_value=("C:\\Tools", 2),
                ),
                mock.patch("scripts.gar_lib.launcher_setup._write_windows_user_path") as write_path,
                mock.patch("scripts.gar_lib.launcher_setup._broadcast_windows_environment_change") as broadcast,
            ):
                result = offer_scripts_path_registration(
                    scripts,
                    stdin=TtyInput("\n"),
                    stdout=output,
                    environ={"PATH": ""},
                    platform="nt",
                )

        self.assertEqual(0, result)
        write_path.assert_called_once_with(f"C:\\Tools;{scripts.resolve()}", 2)
        broadcast.assert_called_once_with()
        self.assertIn("[Y/n]", output.getvalue())
        self.assertIn("現在のterminalには未反映", output.getvalue())
        self.assertIn(r".\scripts\gar.cmd <command>", output.getvalue())

    def test_no_answer_keeps_path_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scripts = Path(temporary_directory) / "scripts"
            scripts.mkdir()
            output = io.StringIO()
            with (
                mock.patch("scripts.gar_lib.launcher_setup._read_windows_user_path", return_value=("", 2)),
                mock.patch("scripts.gar_lib.launcher_setup._write_windows_user_path") as write_path,
            ):
                result = offer_scripts_path_registration(
                    scripts,
                    stdin=TtyInput("n\n"),
                    stdout=output,
                    environ={"PATH": ""},
                    platform="nt",
                )

        self.assertEqual(0, result)
        write_path.assert_not_called()
        self.assertIn("PATH登録をSKIPしました", output.getvalue())

    def test_posix_default_yes_adds_one_profile_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            scripts = home / "repo" / "scripts"
            scripts.mkdir(parents=True)
            output = io.StringIO()

            result = offer_scripts_path_registration(
                scripts,
                stdin=TtyInput("\n"),
                stdout=output,
                environ={"PATH": "/usr/bin", "HOME": str(home), "SHELL": "/bin/bash"},
                platform="posix",
            )
            profile = (home / ".bashrc").read_text(encoding="utf-8")

        self.assertEqual(0, result)
        self.assertIn(str(scripts.resolve()), profile)
        self.assertIn('"$PATH"', profile)
        self.assertIn("shell profileを再読込", output.getvalue())

    def test_noninteractive_setup_does_not_change_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scripts = Path(temporary_directory) / "scripts"
            scripts.mkdir()
            output = io.StringIO()
            with (
                mock.patch("scripts.gar_lib.launcher_setup._read_windows_user_path", return_value=("", 2)),
                mock.patch("scripts.gar_lib.launcher_setup._write_windows_user_path") as write_path,
            ):
                result = offer_scripts_path_registration(
                    scripts,
                    stdin=io.StringIO(""),
                    stdout=output,
                    environ={"PATH": ""},
                    platform="nt",
                )

        self.assertEqual(0, result)
        write_path.assert_not_called()
        self.assertIn("非対話実行", output.getvalue())

    def test_bash_completion_is_generated_and_registered_from_setup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve() / "repo"
            scripts = root / "scripts"
            scripts.mkdir(parents=True)
            home = Path(temporary_directory) / "home"
            output = io.StringIO()

            result = offer_shell_completion_registration(
                scripts,
                stdin=TtyInput("\n"),
                stdout=output,
                environ={"HOME": str(home), "SHELL": "/bin/bash"},
                platform="posix",
            )

            completion = (root / ".gar" / "completion" / "gar.bash").read_text(encoding="utf-8")
            profile = (home / ".bashrc").read_text(encoding="utf-8")

        self.assertEqual(0, result)
        self.assertIn(str(scripts / "gar"), completion)
        self.assertIn("completion words", completion)
        self.assertIn(COMPLETION_BLOCK_START, profile)
        self.assertIn(COMPLETION_BLOCK_END, profile)
        self.assertIn("Bash補完を登録しました", output.getvalue())

    def test_completion_registration_is_idempotent_and_skips_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "repo"
            scripts = root / "scripts"
            scripts.mkdir(parents=True)
            home = Path(temporary_directory) / "home"
            environment = {"HOME": str(home), "SHELL": "/bin/zsh"}

            first = offer_shell_completion_registration(
                scripts,
                stdin=TtyInput("\n"),
                stdout=io.StringIO(),
                environ=environment,
                platform="posix",
            )
            output = io.StringIO()
            second = offer_shell_completion_registration(
                scripts,
                stdin=TtyInput("n\n"),
                stdout=output,
                environ=environment,
                platform="posix",
            )
            profile = (home / ".zshrc").read_text(encoding="utf-8")

        self.assertEqual(0, first)
        self.assertEqual(0, second)
        self.assertEqual(1, profile.count(COMPLETION_BLOCK_START))
        self.assertIn("Zsh補完は登録済み", output.getvalue())
        self.assertNotIn("[Y/n]", output.getvalue())

    def test_completion_registration_replaces_all_stale_managed_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "repo"
            scripts = root / "scripts"
            scripts.mkdir(parents=True)
            home = Path(temporary_directory) / "home"
            home.mkdir()
            profile = home / ".bashrc"
            stale = (
                f"{COMPLETION_BLOCK_START}\n. /old/one\n{COMPLETION_BLOCK_END}\n"
                f"{COMPLETION_BLOCK_START}\n. /old/two\n{COMPLETION_BLOCK_END}\n"
            )
            profile.write_text("user setting\n" + stale, encoding="utf-8")

            result = offer_shell_completion_registration(
                scripts,
                stdin=TtyInput("\n"),
                stdout=io.StringIO(),
                environ={"HOME": str(home), "SHELL": "/bin/bash"},
                platform="posix",
            )
            profile_text = profile.read_text(encoding="utf-8")

        self.assertEqual(0, result)
        self.assertEqual(1, profile_text.count(COMPLETION_BLOCK_START))
        self.assertNotIn("/old/one", profile_text)
        self.assertNotIn("/old/two", profile_text)
        self.assertIn("user setting", profile_text)

    def test_windows_completion_registers_detected_powershell_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "repo"
            scripts = root / "scripts"
            scripts.mkdir(parents=True)
            profiles = [
                Path(temporary_directory) / "PowerShell" / "profile.ps1",
                Path(temporary_directory) / "WindowsPowerShell" / "profile.ps1",
            ]
            output = io.StringIO()
            with mock.patch(
                "scripts.gar_lib.launcher_setup._windows_powershell_profiles",
                return_value=profiles,
            ):
                result = offer_shell_completion_registration(
                    scripts,
                    stdin=TtyInput("\n"),
                    stdout=output,
                    environ={},
                    platform="nt",
                )

            completion = (root / ".gar" / "completion" / "gar.ps1").read_text(encoding="utf-8")
            profile_texts = [profile.read_text(encoding="utf-8") for profile in profiles]

        self.assertEqual(0, result)
        self.assertIn("Register-ArgumentCompleter -Native", completion)
        self.assertIn("gar.cmd", completion)
        self.assertTrue(all(COMPLETION_BLOCK_START in text for text in profile_texts))
        self.assertIn("PowerShell補完を登録しました", output.getvalue())

    def test_noninteractive_completion_setup_does_not_write_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            scripts = Path(temporary_directory) / "repo" / "scripts"
            scripts.mkdir(parents=True)
            home = Path(temporary_directory) / "home"
            output = io.StringIO()

            result = offer_shell_completion_registration(
                scripts,
                stdin=io.StringIO(""),
                stdout=output,
                environ={"HOME": str(home), "SHELL": "/bin/bash"},
                platform="posix",
            )

        self.assertEqual(0, result)
        self.assertFalse((home / ".bashrc").exists())
        self.assertIn("非対話実行のためBash補完登録をSKIP", output.getvalue())


class GarBootstrapTest(unittest.TestCase):
    def test_relaunch_skips_when_repository_venv_is_active(self) -> None:
        with mock.patch("scripts.gar_lib.bootstrap.subprocess.run") as run:
            result = relaunch_in_venv(
                Path("launcher"),
                ["--help"],
                environ={"VIRTUAL_ENV": str(VENV)},
            )

        self.assertIsNone(result)
        run.assert_not_called()

    def test_relaunch_uses_repository_python_and_preserves_arguments(self) -> None:
        completed = subprocess.CompletedProcess([], 7)
        with (
            mock.patch("scripts.gar_lib.bootstrap.ensure_venv", return_value=0),
            mock.patch("scripts.gar_lib.bootstrap.subprocess.run", return_value=completed) as run,
        ):
            result = relaunch_in_venv(
                Path("launcher"),
                ["config", "--no-install"],
                environ={"PATH": "tools"},
            )

        self.assertEqual(7, result)
        run.assert_called_once_with(
            [str(VENV_PYTHON), "launcher", "config", "--no-install"],
            env={"PATH": "tools", "GAR_VENV": str(VENV)},
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
