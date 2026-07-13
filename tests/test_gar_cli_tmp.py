from __future__ import annotations

import unittest
from unittest import mock

from scripts.gar_lib.cli_tmp import main
from scripts.gar_lib.core.command import (
    SIM_BUILD,
    SIM_CLEAN,
    SIM_RUNTIME_DEPLOY,
    TARGET_DEPLOY,
)


class GarCliTmpTest(unittest.TestCase):
    def test_sim_build_routes_workspace_to_sim_command(self) -> None:
        with mock.patch("scripts.gar_lib.cli_tmp.run_sim_command", return_value=0) as run:
            result = main(["sim", "build", "--workspace", "Local/GarStreamTx"])

        self.assertEqual(0, result)
        run.assert_called_once_with(
            SIM_BUILD,
            workspace_selector="Local/GarStreamTx",
            retry_command="gar sim build --workspace Local/GarStreamTx",
        )

    def test_sim_build_clean_routes_clean_command(self) -> None:
        with mock.patch("scripts.gar_lib.cli_tmp.run_sim_command", return_value=0) as run:
            result = main(["sim", "build", "clean", "--workspace", "Local/GarStreamRx"])

        self.assertEqual(0, result)
        self.assertEqual(SIM_CLEAN, run.call_args.args[0])

    def test_sim_runtime_deploy_routes_workspace(self) -> None:
        with mock.patch("scripts.gar_lib.cli_tmp.run_sim_command", return_value=0) as run:
            result = main(["sim", "env", "deploy", "--workspace", "Local/GarStreamTx"])

        self.assertEqual(0, result)
        run.assert_called_once_with(
            SIM_RUNTIME_DEPLOY,
            workspace_selector="Local/GarStreamTx",
            retry_command="gar sim env deploy --workspace Local/GarStreamTx",
        )

    def test_sim_host_start_routes_host_options(self) -> None:
        with mock.patch("scripts.gar_lib.cli_tmp.run_sim_host_command", return_value=0) as run:
            result = main(
                ["sim", "start", "--workspace", "Network/GarStreamTx", "--no-update-ssh", "--pull"]
            )

        self.assertEqual(0, result)
        run.assert_called_once_with(
            "start",
            workspace_selector="Network/GarStreamTx",
            retry_command=(
                "gar sim start --workspace Network/GarStreamTx --no-update-ssh --pull"
            ),
            update_address=False,
            update_repository=True,
            json_output=False,
        )

    def test_sim_environment_start_routes_lifecycle_options(self) -> None:
        with mock.patch("scripts.gar_lib.cli_tmp.run_sim_lifecycle", return_value=0) as run:
            result = main(
                [
                    "sim",
                    "env",
                    "start",
                    "--workspace",
                    "Local/GarStreamTx",
                    "--settings",
                    "/tmp/settings.json",
                    "--profile-name",
                    "GAR Sim",
                    "--no-port-forward",
                ]
            )

        self.assertEqual(0, result)
        run.assert_called_once_with(
            "start",
            workspace_selector="Local/GarStreamTx",
            retry_command=(
                "gar sim env start --workspace Local/GarStreamTx --settings /tmp/settings.json "
                "--profile-name 'GAR Sim' --no-port-forward"
            ),
            settings="/tmp/settings.json",
            profile_name="GAR Sim",
            manage_port_forward=False,
        )

    def test_sim_panel_routes_only_present_parameters(self) -> None:
        with mock.patch("scripts.gar_lib.cli_tmp.run_sim_panel", return_value=0) as run:
            result = main(
                [
                    "sim",
                    "env",
                    "panel",
                    "rfid-tap",
                    "--workspace",
                    "Local/GarStreamRx",
                    "--uid",
                    "01:02:03:04",
                    "--json",
                ]
            )

        self.assertEqual(0, result)
        run.assert_called_once_with(
            "rfid-tap",
            workspace_selector="Local/GarStreamRx",
            retry_command=(
                "gar sim env panel rfid-tap --workspace Local/GarStreamRx "
                "--uid 01:02:03:04 --json"
            ),
            json_output=True,
            params={"duration_ms": 150, "uid": "01:02:03:04"},
        )

    def test_target_deploy_routes_workspace_to_target_command(self) -> None:
        with mock.patch("scripts.gar_lib.cli_tmp.run_target_command", return_value=0) as run:
            result = main(["target", "deploy", "--workspace", "Local/GarStreamTx"])

        self.assertEqual(0, result)
        run.assert_called_once_with(
            TARGET_DEPLOY,
            workspace_selector="Local/GarStreamTx",
            retry_command="gar target deploy --workspace Local/GarStreamTx",
        )


if __name__ == "__main__":
    unittest.main()
