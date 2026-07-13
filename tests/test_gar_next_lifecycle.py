from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest import mock

from scripts.gar_lib.commands.sim_entry import (
    run_next_sim_diagnostic,
    run_next_sim_host_command,
    run_next_sim_lifecycle,
)
from scripts.gar_lib.core.errors import AccessConnectionError
from scripts.gar_lib.simulation.diagnostic import SimulationDiagnostic
from scripts.gar_lib.simulation.host import SimulationHostState


class GarNextLifecycleTest(unittest.TestCase):
    def test_host_aws_authentication_failure_uses_terminal_bridge_recovery(self) -> None:
        workspace = mock.Mock(name="workspace", ec2={"region": "ap-northeast-1"})
        workspace.name = "Local/Product"
        controller = mock.Mock()
        controller.status.side_effect = AccessConnectionError(
            channel="aws",
            endpoint="ap-northeast-1",
            reason="authentication",
            returncode=255,
        )
        with (
            mock.patch("scripts.gar_lib.commands.sim_entry.ConfigWorkspaceRegistry") as registry_type,
            mock.patch(
                "scripts.gar_lib.commands.sim_entry.ConfigSimulationHostControllerResolver"
            ) as resolver_type,
            mock.patch(
                "scripts.gar_lib.commands.sim_entry.run_terminal_request", return_value=0
            ) as terminal_request,
        ):
            registry_type.return_value.get.return_value = workspace
            resolver_type.return_value.for_workspace.return_value = controller
            with contextlib.redirect_stderr(io.StringIO()):
                result = run_next_sim_host_command(
                    "status",
                    workspace_selector="Local/Product",
                    retry_command="gar sim status --workspace Local/Product",
                )

        self.assertEqual(1, result)
        self.assertEqual(
            "aws login --remote --region ap-northeast-1",
            terminal_request.call_args.kwargs["command_text"],
        )

    def test_host_status_serializes_controller_result(self) -> None:
        workspace = mock.Mock()
        controller = mock.Mock()
        controller.status.return_value = SimulationHostState(
            host="sim-host",
            instance_id="i-test",
            region="ap-northeast-1",
            state="running",
            public_ip="203.0.113.5",
        )
        with (
            mock.patch("scripts.gar_lib.commands.sim_entry.ConfigWorkspaceRegistry") as registry_type,
            mock.patch(
                "scripts.gar_lib.commands.sim_entry.ConfigSimulationHostControllerResolver"
            ) as resolver_type,
        ):
            registry_type.return_value.get.return_value = workspace
            resolver_type.return_value.for_workspace.return_value = controller
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_next_sim_host_command(
                    "status",
                    workspace_selector="Local/Product",
                    retry_command="gar sim status --workspace Local/Product",
                    json_output=True,
                )

        self.assertEqual(0, result)
        payload = json.loads(output.getvalue())
        self.assertEqual("i-test", payload["instance_id"])
        self.assertTrue(payload["running"])
        controller.status.assert_called_once_with()

    def test_diag_serializes_environment_result_with_workspace_host(self) -> None:
        workspace = mock.Mock(ec2={"host": "sim-host"})
        environment = mock.Mock()
        environment.diag.return_value = SimulationDiagnostic(
            processes=[{"pid": 123, "cmd": "bridge.py"}],
            devices={"/dev/i2c-1": True},
            api={"ready": True},
            ok=True,
        )
        with (
            mock.patch("scripts.gar_lib.commands.sim_entry.ConfigWorkspaceRegistry") as registry_type,
            mock.patch(
                "scripts.gar_lib.commands.sim_entry.ConfigSimulationEnvironmentResolver"
            ) as resolver_type,
            mock.patch("scripts.gar_lib.commands.sim_entry.load_hw_definition", return_value={}),
        ):
            registry_type.return_value.get.return_value = workspace
            resolver_type.return_value.for_workspace.return_value = environment
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = run_next_sim_diagnostic(
                    workspace_selector="Local/Product",
                    retry_command="gar sim env diag --json --workspace Local/Product",
                )

        self.assertEqual(0, result)
        self.assertEqual("sim-host", json.loads(output.getvalue())["host"])
        environment.diag.assert_called_once_with({})

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
