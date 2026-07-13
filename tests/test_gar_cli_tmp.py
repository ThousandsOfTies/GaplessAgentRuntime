from __future__ import annotations

import unittest
from unittest import mock

from scripts.gar_lib.application import CommandOutcome
from scripts.gar_lib.cli_tmp import main, sim_command, target_command
from scripts.gar_lib.core.command import (
    SIM_BUILD,
    SIM_CLEAN,
    SIM_DEPLOY,
    SIM_RUNTIME_BUILD,
    SIM_RUNTIME_DEPLOY,
    TARGET_BUILD,
    TARGET_DEPLOY,
)


class GarCliTmpTest(unittest.TestCase):
    def test_sim_arguments_map_to_domain_commands(self) -> None:
        self.assertEqual(SIM_BUILD, sim_command(["build"]))
        self.assertEqual(SIM_CLEAN, sim_command(["build", "clean"]))
        self.assertEqual(SIM_DEPLOY, sim_command(["deploy"]))
        self.assertEqual(SIM_RUNTIME_BUILD, sim_command(["env", "build"]))
        self.assertEqual(SIM_RUNTIME_DEPLOY, sim_command(["env", "deploy"]))

    def test_target_arguments_map_to_domain_commands(self) -> None:
        self.assertEqual(TARGET_BUILD, target_command("build"))
        self.assertEqual(TARGET_DEPLOY, target_command("deploy"))

    def test_sim_build_composes_application_and_dispatches(self) -> None:
        services = mock.Mock()
        outcome = CommandOutcome(mock.Mock(), artifact=mock.Mock())
        with (
            mock.patch("scripts.gar_lib.cli_tmp.compose_application", return_value=services),
            mock.patch("scripts.gar_lib.cli_tmp.dispatch", return_value=outcome) as dispatch,
            mock.patch("scripts.gar_lib.cli_tmp.render_outcome") as render,
        ):
            result = main(["sim", "build", "--workspace", "Local/GarStreamTx"])

        self.assertEqual(0, result)
        dispatch.assert_called_once_with(
            SIM_BUILD,
            workspace_selector="Local/GarStreamTx",
            services=services,
        )
        render.assert_called_once_with(SIM_BUILD, outcome, json_output=False)

    def test_target_deploy_uses_same_application_dispatch(self) -> None:
        services = mock.Mock()
        outcome = CommandOutcome(mock.Mock(), artifact=mock.Mock())
        with (
            mock.patch("scripts.gar_lib.cli_tmp.compose_application", return_value=services),
            mock.patch("scripts.gar_lib.cli_tmp.dispatch", return_value=outcome) as dispatch,
            mock.patch("scripts.gar_lib.cli_tmp.render_outcome"),
        ):
            result = main(["target", "deploy", "--workspace", "Network/GarStreamTx"])

        self.assertEqual(0, result)
        dispatch.assert_called_once_with(
            TARGET_DEPLOY,
            workspace_selector="Network/GarStreamTx",
            services=services,
        )


if __name__ == "__main__":
    unittest.main()
