from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from scripts.gar_lib.commands.setup.workspace_setup import (
    _prompt_local_connection,
    configure_workspace_root,
)


class WorkspaceSetupTests(unittest.TestCase):
    def test_registered_workspace_overview_is_unnumbered_and_has_blank_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = {
                "workspaces": [
                    {
                        "id": "rx",
                        "name": "Local/GarStreamRx",
                        "connection": {"type": "local", "path": tmp},
                        "branch": "GarStreamRx",
                    }
                ]
            }
            output = io.StringIO()
            with (
                mock.patch(
                    "scripts.gar_lib.commands.setup.workspace_setup.safe_input",
                    return_value="",
                ),
                mock.patch(
                    "scripts.gar_lib.commands.setup.workspace_setup.sys.stdin.isatty",
                    return_value=True,
                ),
                redirect_stdout(output),
            ):
                selected = configure_workspace_root(config)

        text = output.getvalue()
        self.assertEqual("rx", selected)
        self.assertIn("    Local/GarStreamRx", text)
        self.assertNotIn("    1. Local/GarStreamRx", text)
        self.assertTrue(text.endswith("\n\n"))

    def test_empty_local_path_keeps_existing_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            existing_path = Path(tmp).resolve()
            with (
                mock.patch(
                    "scripts.gar_lib.commands.setup.workspace_setup.safe_input",
                    return_value="",
                ),
                mock.patch(
                    "scripts.gar_lib.commands.setup.workspace_setup.probe_git_workspace",
                    return_value=("origin", "GarStreamTx"),
                ),
            ):
                connection, branch = _prompt_local_connection({"path": str(existing_path)}, None)

        self.assertEqual({"type": "local", "path": str(existing_path)}, connection)
        self.assertEqual("GarStreamTx", branch)

    def test_successful_edit_moves_to_next_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {
                "workspaces": [
                    {
                        "id": "rx",
                        "name": "Local/GarStreamRx",
                        "connection": {"type": "local", "path": str(root)},
                        "branch": "GarStreamRx",
                    },
                    {
                        "id": "tx",
                        "name": "Local/GarStreamTx",
                        "connection": {"type": "local", "path": str(root)},
                        "branch": "GarStreamTx",
                        "selected_target": "linux-device",
                        "selected_environments": {
                            "codespace": "local",
                            "simulator": "ssh_remote",
                            "target": "ssh_scp",
                        },
                        "ec2": {"host": "vibecode-graviton-tx"},
                        "target": {"host": "garstream-tx-device"},
                    },
                ],
            }
            with (
                mock.patch(
                    "scripts.gar_lib.commands.setup.workspace_setup.safe_input",
                    side_effect=["e", "2", "", ""],
                ),
                mock.patch(
                    "scripts.gar_lib.commands.setup.workspace_setup.probe_git_workspace",
                    return_value=("origin", "GarStreamTx"),
                ),
                mock.patch(
                    "scripts.gar_lib.commands.setup.workspace_setup.sys.stdin.isatty",
                    return_value=True,
                ),
                mock.patch("scripts.gar_lib.commands.setup.workspace_setup.save_config"),
                mock.patch("scripts.gar_lib.commands.setup.workspace_setup._select_active_workspace") as select_active,
                redirect_stdout(io.StringIO()) as output,
            ):
                selected = configure_workspace_root(config)

        self.assertEqual("tx", selected)
        select_active.assert_not_called()
        saved_tx = next(entry for entry in config["workspaces"] if entry["id"] == "tx")
        self.assertEqual("linux-device", saved_tx["selected_target"])
        self.assertEqual("ssh_remote", saved_tx["selected_environments"]["simulator"])
        self.assertEqual("vibecode-graviton-tx", saved_tx["ec2"]["host"])
        self.assertEqual("garstream-tx-device", saved_tx["target"]["host"])
        self.assertIn("    2. Local/GarStreamTx", output.getvalue())


if __name__ == "__main__":
    unittest.main()
