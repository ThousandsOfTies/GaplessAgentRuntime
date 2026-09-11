import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.gar_lib.cli import main
from scripts.gar_lib.commands.code import (
    run_code_command,
    shutdown_code_codespace,
    start_code_codespace,
    stop_code_codespace,
)
from scripts.gar_lib.core.workspace import Workspace


class GarCodeCliTest(unittest.TestCase):
    def test_code_start_is_available_from_cli(self) -> None:
        with mock.patch("scripts.gar_lib.commands.code.run_code_command", return_value=0) as run_code:
            result = main(["code", "start", "--codespace", "codespace-test", "--no-mount"])

        self.assertEqual(0, result)
        run_code.assert_called_once_with(
            "start",
            workspace_selector=None,
            codespace="codespace-test",
            remote_path=None,
            mount_dir=None,
            settings=None,
            profile_name=None,
            no_mount=True,
            shutdown=False,
        )

    def test_code_boot_is_available_from_cli(self) -> None:
        with mock.patch("scripts.gar_lib.commands.code.run_code_command", return_value=0) as run_code:
            result = main(["code", "boot", "--codespace", "codespace-test"])

        self.assertEqual(0, result)
        run_code.assert_called_once_with(
            "boot",
            workspace_selector=None,
            codespace="codespace-test",
            remote_path=None,
            mount_dir=None,
            settings=None,
            profile_name=None,
            no_mount=False,
            shutdown=False,
        )

    def test_code_status_is_available_from_cli(self) -> None:
        with (
            mock.patch("scripts.gar_lib.commands.code.resolve_workspace") as resolve,
            mock.patch("scripts.gar_lib.commands.code.observe_code") as observe,
            mock.patch("scripts.gar_lib.commands.code.render_observation", return_value=0),
        ):
            result = main(["code", "status", "--codespace", "codespace-test", "--mount-dir", "/tmp/codespaces"])
        self.assertEqual(0, result)
        observe.assert_called_once_with(
            resolve.return_value, action="status", codespace="codespace-test", mount_dir="/tmp/codespaces"
        )

    def test_code_command_uses_selected_codespaces_environment(self) -> None:
        workspace = Workspace(
            id="workspace-test",
            name="GitHub/Product",
            branch="main",
            connection={
                "type": "codespaces",
                "codespace": "configured-codespace",
                "path": "/workspaces/product",
            },
            selected_environments={"codespace": "github_codespaces"},
        )
        with (
            mock.patch(
                "scripts.gar_lib.commands.code.resolve_workspace",
                return_value=workspace,
            ),
            mock.patch(
                "scripts.gar_lib.commands.code.boot_code_codespace",
                return_value=0,
            ) as boot,
        ):
            result = run_code_command("boot", codespace="selected-target")

        self.assertEqual(0, result)
        boot.assert_called_once_with(codespace="selected-target", gh_timeout=None)

    def test_code_command_defaults_to_local_environment(self) -> None:
        workspace = Workspace(
            id="workspace-test",
            name="Local/Product",
            branch="main",
            connection={"type": "local", "path": "/tmp/product"},
        )
        with (
            mock.patch(
                "scripts.gar_lib.commands.code.resolve_workspace",
                return_value=workspace,
            ),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            result = run_code_command("status")

        self.assertEqual(0, result)
        self.assertIn("Local development environment: available", output.getvalue())

    def test_code_start_writes_codespace_state_and_terminal_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            cwd = home / "workspace"
            cwd.mkdir()
            settings = home / "settings.json"

            def run_side_effect(argv, **kwargs):
                completed = mock.Mock()
                completed.returncode = 0
                completed.stdout = ""
                if argv[:4] == ["gh", "codespace", "ssh", "-c"]:
                    completed.stdout = "Host codespace-host\n  HostName example\n"
                return completed

            with (
                mock.patch("scripts.gar_lib.commands.code.Path.home", return_value=home),
                mock.patch("scripts.gar_lib.commands.code.shutil.which", return_value="/usr/bin/tool"),
                mock.patch("scripts.gar_lib.commands.code.subprocess.run", side_effect=run_side_effect),
            ):
                output = io.StringIO()
                with contextlib.chdir(cwd), contextlib.redirect_stdout(output):
                    result = start_code_codespace(
                        codespace="codespace-test",
                        settings=str(settings),
                        no_mount=True,
                    )

            self.assertEqual(0, result)
            self.assertEqual(
                "Host codespace-host\n  HostName example\n",
                (home / ".ssh" / "codespaces").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "Include ~/.ssh/codespaces",
                (home / ".ssh" / "config").read_text(encoding="utf-8"),
            )
            state = json.loads((home / ".config" / "codespace-dev" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual("codespace-test", state["codespace_name"])
            self.assertEqual("codespace-host", state["ssh_host"])
            self.assertEqual("/workspaces/gar-build-env", state["remote_path"])
            self.assertEqual(str(cwd / "codespaces"), state["mount_dir"])
            terminal = home / ".local" / "bin" / "codespace-terminal"
            self.assertIn("Run: gar code start", terminal.read_text(encoding="utf-8"))
            profile = json.loads(settings.read_text(encoding="utf-8"))
            platform_name = "windows" if os.name == "nt" else "linux"
            expected_profile = (
                {"path": str(Path(sys.executable)), "args": [str(terminal)]}
                if os.name == "nt"
                else {"path": str(terminal)}
            )
            self.assertEqual(
                expected_profile,
                profile[f"terminal.integrated.profiles.{platform_name}"]["Codespaces"],
            )

    def test_code_start_times_out_when_gh_ssh_config_hangs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings = home / "settings.json"

            def run_side_effect(argv, **kwargs):
                if argv[:4] == ["gh", "codespace", "ssh", "-c"]:
                    raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
                completed = mock.Mock()
                completed.returncode = 0
                completed.stdout = ""
                return completed

            with (
                mock.patch("scripts.gar_lib.commands.code.Path.home", return_value=home),
                mock.patch("scripts.gar_lib.commands.code.shutil.which", return_value="/usr/bin/tool"),
                mock.patch("scripts.gar_lib.commands.code.subprocess.run", side_effect=run_side_effect),
            ):
                stderr = io.StringIO()
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    result = start_code_codespace(
                        codespace="codespace-test",
                        settings=str(settings),
                        no_mount=True,
                        gh_timeout=3,
                    )

            self.assertEqual(1, result)
            self.assertIn("timed out after 3s", stderr.getvalue())
            self.assertFalse((home / ".ssh" / "codespaces").exists())

    def test_code_start_without_codespace_uses_single_listed_codespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings = home / "settings.json"

            def run_side_effect(argv, **kwargs):
                completed = mock.Mock()
                completed.returncode = 0
                completed.stdout = ""
                if argv == ["gh", "codespace", "list"]:
                    completed.stdout = "single-codespace\towner/repo\tmain\tStopped\tShutdown\t1h\n"
                if argv[:4] == ["gh", "codespace", "ssh", "-c"]:
                    completed.stdout = "Host codespace-host\n  HostName example\n"
                return completed

            with (
                mock.patch("scripts.gar_lib.commands.code.Path.home", return_value=home),
                mock.patch("scripts.gar_lib.commands.code.shutil.which", return_value="/usr/bin/tool"),
                mock.patch("scripts.gar_lib.commands.code.subprocess.run", side_effect=run_side_effect) as run,
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = start_code_codespace(settings=str(settings), no_mount=True)

            self.assertEqual(0, result)
            gh_ssh_calls = [
                call.args[0] for call in run.call_args_list if call.args[0][:4] == ["gh", "codespace", "ssh", "-c"]
            ]
            self.assertEqual(
                ["gh", "codespace", "ssh", "-c", "single-codespace", "--config"],
                gh_ssh_calls[0],
            )

    def test_code_start_detects_workspace_when_default_build_env_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings = home / "settings.json"

            def run_side_effect(argv, **kwargs):
                completed = mock.Mock()
                completed.returncode = 0
                completed.stdout = ""
                if argv[:5] == ["gh", "codespace", "ssh", "-c", "codespace-test"] and argv[-1] == "--config":
                    completed.stdout = "Host codespace-host\n  HostName example\n"
                elif argv[:5] == ["gh", "codespace", "ssh", "-c", "codespace-test"] and "test -d" in argv[-1]:
                    completed.returncode = 1
                elif argv[:5] == ["gh", "codespace", "ssh", "-c", "codespace-test"] and "find /workspaces" in argv[-1]:
                    completed.stdout = "/workspaces/build-hub\n"
                return completed

            with (
                mock.patch("scripts.gar_lib.commands.code.Path.home", return_value=home),
                mock.patch("scripts.gar_lib.commands.code.shutil.which", return_value="/usr/bin/tool"),
                mock.patch("scripts.gar_lib.commands.code.subprocess.run", side_effect=run_side_effect),
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = start_code_codespace(
                        codespace="codespace-test",
                        settings=str(settings),
                        no_mount=True,
                    )

            self.assertEqual(0, result)
            state = json.loads((home / ".config" / "codespace-dev" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual("/workspaces/build-hub", state["remote_path"])
            self.assertIn("Remote path not found: /workspaces/gar-build-env", output.getvalue())

    def test_code_stop_is_available_from_cli(self) -> None:
        with mock.patch("scripts.gar_lib.commands.code.run_code_command", return_value=0) as run_code:
            result = main(["code", "stop"])

        self.assertEqual(0, result)
        run_code.assert_called_once_with(
            "stop",
            workspace_selector=None,
            codespace=None,
            remote_path=None,
            mount_dir=None,
            settings=None,
            profile_name=None,
            no_mount=False,
            shutdown=False,
        )

    def test_code_shutdown_is_available_from_cli(self) -> None:
        with mock.patch("scripts.gar_lib.commands.code.run_code_command", return_value=0) as run_code:
            result = main(["code", "shutdown", "--codespace", "codespace-test"])

        self.assertEqual(0, result)
        run_code.assert_called_once_with(
            "shutdown",
            workspace_selector=None,
            codespace="codespace-test",
            remote_path=None,
            mount_dir=None,
            settings=None,
            profile_name=None,
            no_mount=False,
            shutdown=False,
        )

    def test_code_stop_shutdown_flag_is_available_from_cli(self) -> None:
        with mock.patch("scripts.gar_lib.commands.code.run_code_command", return_value=0) as run_code:
            result = main(["code", "stop", "--shutdown", "--codespace", "codespace-test"])

        self.assertEqual(0, result)
        run_code.assert_called_once_with(
            "stop",
            workspace_selector=None,
            codespace="codespace-test",
            remote_path=None,
            mount_dir=None,
            settings=None,
            profile_name=None,
            no_mount=False,
            shutdown=True,
        )

    def test_code_stop_unmounts_codespace_and_removes_terminal_profile_on_posix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            mount_dir = home / "codespaces" / "gar-build-env"
            mount_dir.mkdir(parents=True)
            state_dir = home / ".config" / "codespace-dev"
            state_dir.mkdir(parents=True)
            (state_dir / "env").write_text(
                "\n".join(
                    [
                        "CODESPACE_SSH_HOST='codespace-host'",
                        "CODESPACE_REMOTE_PATH='/workspaces/gar-build-env'",
                        f"CODESPACE_MOUNT_DIR='{mount_dir}'",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            settings = home / "settings.json"
            settings.write_text(
                json.dumps(
                    {
                        "terminal.integrated.profiles.linux": {
                            "Codespaces": {"path": str(home / ".local" / "bin" / "codespace-terminal")},
                            "bash": {"path": "/bin/bash"},
                        }
                    }
                ),
                encoding="utf-8",
            )

            def run_side_effect(argv, **kwargs):
                completed = mock.Mock()
                completed.returncode = 0
                completed.stdout = ""
                if argv[:4] == ["findmnt", "-n", "-o", "SOURCE"]:
                    completed.stdout = "codespace-host:/workspaces/gar-build-env\n"
                return completed

            with (
                mock.patch("scripts.gar_lib.commands.code._is_windows_host", return_value=False),
                mock.patch("scripts.gar_lib.vscode.profile_manage.os", SimpleNamespace(name="posix")),
                mock.patch("scripts.gar_lib.commands.code.Path.home", return_value=home),
                mock.patch("scripts.gar_lib.commands.code.shutil.which", return_value="/usr/bin/tool"),
                mock.patch("scripts.gar_lib.commands.code.subprocess.run", side_effect=run_side_effect) as run,
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = stop_code_codespace(settings=str(settings))

            self.assertEqual(0, result)
            self.assertIn(
                ["/usr/bin/tool", "-u", str(mount_dir)],
                [call.args[0] for call in run.call_args_list],
            )
            profile = json.loads(settings.read_text(encoding="utf-8"))
            profiles = profile["terminal.integrated.profiles.linux"]
            self.assertNotIn("Codespaces", profiles)
            self.assertIn("bash", profiles)

    def test_code_shutdown_stops_explicit_codespace(self) -> None:
        def run_side_effect(argv, **kwargs):
            completed = mock.Mock()
            completed.returncode = 0
            completed.stdout = ""
            return completed

        with mock.patch("scripts.gar_lib.commands.code.subprocess.run", side_effect=run_side_effect) as run:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = shutdown_code_codespace(codespace="codespace-test")

        self.assertEqual(0, result)
        self.assertIn("Stopping Codespace VM: codespace-test", output.getvalue())
        self.assertEqual(
            ["gh", "codespace", "stop", "-c", "codespace-test"],
            run.call_args_list[0].args[0],
        )

    def test_code_stop_can_shutdown_codespace_from_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            state_dir = home / ".config" / "codespace-dev"
            state_dir.mkdir(parents=True)
            mount_dir = home / "codespaces"
            (state_dir / "env").write_text(
                "\n".join(
                    [
                        "CODESPACE_NAME='codespace-test'",
                        "CODESPACE_SSH_HOST='codespace-host'",
                        "CODESPACE_REMOTE_PATH='/workspaces/gar-build-env'",
                        f"CODESPACE_MOUNT_DIR='{mount_dir}'",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            settings = home / "settings.json"
            settings.write_text("{}", encoding="utf-8")

            def run_side_effect(argv, **kwargs):
                completed = mock.Mock()
                completed.returncode = 0
                completed.stdout = ""
                return completed

            with (
                mock.patch("scripts.gar_lib.commands.code.Path.home", return_value=home),
                mock.patch("scripts.gar_lib.commands.code.shutil.which", return_value="/usr/bin/tool"),
                mock.patch("scripts.gar_lib.commands.code.subprocess.run", side_effect=run_side_effect) as run,
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = stop_code_codespace(settings=str(settings), shutdown=True)

            self.assertEqual(0, result)
            self.assertIn(
                ["gh", "codespace", "stop", "-c", "codespace-test"],
                [call.args[0] for call in run.call_args_list],
            )


if __name__ == "__main__":
    unittest.main()
