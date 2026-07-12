from __future__ import annotations

import unittest
from unittest import mock

from scripts.gar_lib.commands.sim_entry import run_next_sim_lifecycle


class GarNextLifecycleTest(unittest.TestCase):
    def test_status_checks_runtime_even_when_port_forward_is_stopped(self) -> None:
        workspace = mock.Mock(ec2={"host": "sim-host"})
        environment = mock.Mock()
        environment.status.return_value = 0
        with (
            mock.patch("scripts.gar_lib.commands.sim_entry.ConfigWorkspaceRegistry") as registry_type,
            mock.patch(
                "scripts.gar_lib.commands.sim_entry.ConfigSimulationEnvironmentResolver"
            ) as resolver_type,
            mock.patch("scripts.gar_lib.commands.sim_entry.load_hw_definition", return_value={}),
            mock.patch("scripts.gar_lib.commands.sim_entry.status_sim_port_forward", return_value=1),
        ):
            registry_type.return_value.get.return_value = workspace
            resolver_type.return_value.for_workspace.return_value = environment
            result = run_next_sim_lifecycle(
                "status",
                workspace_selector="Local/Product",
                retry_command="gar sim env status --workspace Local/Product",
            )

        self.assertEqual(1, result)
        environment.status.assert_called_once_with({})

    def test_start_can_skip_port_forward(self) -> None:
        workspace = mock.Mock(ec2={"host": "sim-host"})
        environment = mock.Mock()
        environment.start.return_value = 0
        with (
            mock.patch("scripts.gar_lib.commands.sim_entry.ConfigWorkspaceRegistry") as registry_type,
            mock.patch(
                "scripts.gar_lib.commands.sim_entry.ConfigSimulationEnvironmentResolver"
            ) as resolver_type,
            mock.patch("scripts.gar_lib.commands.sim_entry.load_hw_definition", return_value={}),
            mock.patch("scripts.gar_lib.commands.sim_entry.write_sim_terminal_profile"),
            mock.patch("scripts.gar_lib.commands.sim_entry.start_sim_port_forward") as start_forward,
        ):
            registry_type.return_value.get.return_value = workspace
            resolver_type.return_value.for_workspace.return_value = environment
            result = run_next_sim_lifecycle(
                "start",
                workspace_selector="Local/Product",
                retry_command="gar sim env start --workspace Local/Product",
                manage_port_forward=False,
            )

        self.assertEqual(0, result)
        start_forward.assert_not_called()
