from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.gar_lib.commands.code import run_code_command, start_code_codespace
from scripts.gar_lib.commands.code_connection import (
    first_ssh_host,
    mount_codespace_code,
    remote_path_exists,
)
from scripts.gar_lib.commands.code_state import (
    CodespaceConnectionState,
    codespace_terminal_script,
    load_connection_state,
)
from scripts.gar_lib.core.workspace import Workspace


class GarCodeTest(unittest.TestCase):
    def test_workspace_connection_supplies_start_defaults(self) -> None:
        workspace = Workspace(
            id="workspace-test",
            name="GitHub/Product",
            branch="main",
            connection={
                "type": "codespaces",
                "codespace": "configured-codespace",
                "path": "/workspaces/configured product",
            },
            selected_environments={"codespace": "github_codespaces"},
        )

        with (
            mock.patch(
                "scripts.gar_lib.commands.code.resolve_workspace",
                return_value=workspace,
            ) as resolve_workspace,
            mock.patch(
                "scripts.gar_lib.commands.code.start_code_codespace",
                return_value=0,
            ) as start_codespace,
        ):
            result = run_code_command(
                "start",
                workspace_selector="GitHub/Product",
                no_mount=True,
            )

        self.assertEqual(0, result)
        resolve_workspace.assert_called_once_with("GitHub/Product")
        start_codespace.assert_called_once_with(
            codespace="configured-codespace",
            remote_path="/workspaces/configured product",
            mount_dir=None,
            settings=None,
            profile_name=None,
            no_mount=True,
            gh_timeout=None,
        )

    def test_connection_state_round_trips_json_values_with_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            expected = CodespaceConnectionState(
                codespace_name="codespace-test",
                ssh_host="codespace-host",
                remote_path="/workspaces/O'Brien app",
                mount_dir=Path(tmp) / 'mount "quoted"',
            )

            expected.write(state_path)

            self.assertEqual(expected, CodespaceConnectionState.load(state_path))
            if os.name == "posix":
                self.assertEqual(0o600, state_path.stat().st_mode & 0o777)
            self.assertEqual(
                "/workspaces/O'Brien app",
                json.loads(state_path.read_text(encoding="utf-8"))["remote_path"],
            )

    def test_legacy_state_is_migrated_to_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            state_dir = home / ".config" / "codespace-dev"
            state_dir.mkdir(parents=True)
            mount_dir = home / "mount with spaces"
            legacy_path = state_dir / "env"
            legacy_path.write_text(
                "\n".join(
                    [
                        "CODESPACE_NAME=codespace-test",
                        "CODESPACE_SSH_HOST=codespace-host",
                        f"CODESPACE_REMOTE_PATH={shlex.quote('/workspaces/product app')}",
                        f"CODESPACE_MOUNT_DIR={shlex.quote(str(mount_dir))}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            state = load_connection_state(home)

            self.assertIsNotNone(state)
            assert state is not None
            self.assertEqual("/workspaces/product app", state.remote_path)
            self.assertEqual(mount_dir, state.mount_dir)
            self.assertTrue(legacy_path.exists())
            self.assertEqual(state, CodespaceConnectionState.load(state_dir / "state.json"))

    def test_remote_path_check_quotes_shell_metacharacters(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        remote_path = "/workspaces/O'Brien app; echo unsafe"

        with mock.patch(
            "scripts.gar_lib.commands.code_connection.subprocess.run",
            return_value=completed,
        ) as run:
            exists = remote_path_exists("codespace-test", remote_path)

        self.assertTrue(exists)
        self.assertEqual(
            f"test -d {shlex.quote(remote_path)}",
            run.call_args.args[0][-1],
        )

    def test_mount_passes_quoted_remote_path_as_one_argument(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mount_dir = Path(tmp) / "mount dir"
            remote_path = "/workspaces/O'Brien app"
            not_mounted = subprocess.CompletedProcess([], 1)
            mounted = subprocess.CompletedProcess([], 0)

            with mock.patch(
                "scripts.gar_lib.commands.code_connection.subprocess.run",
                side_effect=[not_mounted, mounted],
            ) as run:
                result = mount_codespace_code(
                    host="codespace-host",
                    remote_path=remote_path,
                    mount_dir=mount_dir,
                )

            self.assertEqual(0, result)
            sshfs_argv = run.call_args_list[1].args[0]
            self.assertEqual("codespace-host:/workspaces/O'Brien app", sshfs_argv[1])
            self.assertEqual(str(mount_dir), sshfs_argv[2])

    def test_terminal_launcher_shell_quotes_remote_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            remote_path = "/workspaces/O'Brien app; echo unsafe"
            CodespaceConnectionState(
                codespace_name="codespace-test",
                ssh_host="codespace-host",
                remote_path=remote_path,
                mount_dir=Path(tmp) / "mount",
            ).write(state_path)

            with (
                mock.patch.dict(os.environ, {"CODESPACE_DEV_STATE": str(state_path)}),
                mock.patch("os.execvp") as execvp,
            ):
                exec(compile(codespace_terminal_script(), "codespace-terminal", "exec"), {})

            execvp.assert_called_once_with(
                "ssh",
                [
                    "ssh",
                    "-t",
                    "codespace-host",
                    f"cd {shlex.quote(remote_path)} && exec bash -l",
                ],
            )

    def test_start_does_not_commit_state_when_posix_mount_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings = home / "settings.json"
            with (
                mock.patch("scripts.gar_lib.commands.code._is_windows_host", return_value=False),
                mock.patch("scripts.gar_lib.commands.code.Path.home", return_value=home),
                mock.patch("scripts.gar_lib.commands.code.shutil.which", return_value="/usr/bin/tool"),
                mock.patch(
                    "scripts.gar_lib.commands.code.configure_codespace_ssh",
                    return_value="codespace-host",
                ),
                mock.patch(
                    "scripts.gar_lib.commands.code.resolve_codespace_remote_path",
                    return_value="/workspaces/product",
                ),
                mock.patch(
                    "scripts.gar_lib.commands.code.mount_codespace_code",
                    return_value=9,
                ),
                mock.patch("scripts.gar_lib.commands.code.configure_vscode_codespace") as configure_vscode,
            ):
                result = start_code_codespace(
                    codespace="codespace-test",
                    settings=str(settings),
                )

            self.assertEqual(9, result)
            self.assertFalse((home / ".config" / "codespace-dev" / "state.json").exists())
            configure_vscode.assert_not_called()

    def test_start_steps_run_in_mount_state_vscode_report_order_on_posix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            events: list[str] = []

            def record_mount(**_kwargs) -> int:
                events.append("mount")
                return 0

            def record_state(_state, _path) -> None:
                events.append("state")

            def record_vscode(_options) -> None:
                events.append("vscode")

            def record_report(_options, _state) -> None:
                events.append("report")

            with (
                mock.patch("scripts.gar_lib.commands.code._is_windows_host", return_value=False),
                mock.patch("scripts.gar_lib.commands.code.Path.home", return_value=home),
                mock.patch("scripts.gar_lib.commands.code.shutil.which", return_value="/usr/bin/tool"),
                mock.patch(
                    "scripts.gar_lib.commands.code.configure_codespace_ssh",
                    return_value="codespace-host",
                ),
                mock.patch(
                    "scripts.gar_lib.commands.code.resolve_codespace_remote_path",
                    return_value="/workspaces/product",
                ),
                mock.patch(
                    "scripts.gar_lib.commands.code.mount_codespace_code",
                    side_effect=record_mount,
                ),
                mock.patch.object(CodespaceConnectionState, "write", autospec=True, side_effect=record_state),
                mock.patch(
                    "scripts.gar_lib.commands.code.configure_vscode_codespace",
                    side_effect=record_vscode,
                ),
                mock.patch(
                    "scripts.gar_lib.commands.code.report_codespace_start",
                    side_effect=record_report,
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = start_code_codespace(
                    codespace="codespace-test",
                    settings=str(home / "settings.json"),
                )

            self.assertEqual(0, result)
            self.assertEqual(["mount", "state", "vscode", "report"], events)

    def test_ssh_config_ignores_wildcard_hosts(self) -> None:
        config = "Host *\n  ServerAliveInterval 15\nHost concrete-host\n  HostName example\n"

        self.assertEqual("concrete-host", first_ssh_host(config))


if __name__ == "__main__":
    unittest.main()
