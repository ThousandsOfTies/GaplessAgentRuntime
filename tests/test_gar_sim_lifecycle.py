from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest import mock

from scripts.gar_lib.application import ApplicationServices, dispatch
from scripts.gar_lib.commands.application import execute_application_command, render_outcome
from scripts.gar_lib.core.command import (
    SIM_HOST_STATUS,
    SIM_RUNTIME_DIAG,
    SIM_RUNTIME_START,
    SIM_RUNTIME_STATUS,
)
from scripts.gar_lib.core.errors import AccessConnectionError
from scripts.gar_lib.simulation.diagnostic import SimulationDiagnostic
from scripts.gar_lib.simulation.host import SimulationHostState


def application_services(workspace: object) -> ApplicationServices:
    workspaces = mock.Mock()
    workspaces.get.return_value = workspace
    return ApplicationServices(
        workspaces=workspaces,
        build_environments=mock.Mock(),
        artifacts=mock.Mock(),
        simulation_environments=mock.Mock(),
        simulation_hosts=mock.Mock(),
        simulation_hardware=mock.Mock(),
        simulation_sessions=mock.Mock(),
        target_environments=mock.Mock(),
        hardware=mock.Mock(),
    )


class GarSimulationLifecycleTest(unittest.TestCase):
    def test_host_aws_authentication_failure_uses_terminal_bridge_recovery(self) -> None:
        workspace = mock.Mock(ec2={"region": "ap-northeast-1"})
        workspace.name = "Local/Product"
        services = application_services(workspace)
        controller = services.simulation_hosts.for_workspace.return_value
        controller.status.side_effect = AccessConnectionError(
            channel="aws",
            endpoint="ap-northeast-1",
            reason="authentication",
            returncode=255,
        )
        with (
            mock.patch("scripts.gar_lib.commands.application.compose_application", return_value=services),
            mock.patch(
                "scripts.gar_lib.commands.application.run_terminal_request", return_value=0
            ) as terminal_request,
        ):
            with contextlib.redirect_stderr(io.StringIO()):
                result = execute_application_command(
                    SIM_HOST_STATUS,
                    workspace_selector="Local/Product",
                    retry_command="gar sim status --workspace Local/Product",
                )

        self.assertEqual(1, result)
        self.assertEqual(
            "aws login --remote --region ap-northeast-1",
            terminal_request.call_args.kwargs["command_text"],
        )

    def test_host_status_resolves_controller_and_serializes_result(self) -> None:
        workspace = mock.Mock()
        services = application_services(workspace)
        controller = services.simulation_hosts.for_workspace.return_value
        controller.status.return_value = SimulationHostState(
            host="sim-host",
            instance_id="i-test",
            region="ap-northeast-1",
            state="running",
            public_ip="203.0.113.5",
        )

        outcome = dispatch(
            SIM_HOST_STATUS,
            workspace_selector="Local/Product",
            services=services,
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            render_outcome(SIM_HOST_STATUS, outcome, json_output=True)

        payload = json.loads(output.getvalue())
        self.assertEqual("i-test", payload["instance_id"])
        self.assertTrue(payload["running"])
        services.simulation_hosts.for_workspace.assert_called_once_with(workspace)
        controller.status.assert_called_once_with()

    def test_diag_resolves_environment_and_hardware(self) -> None:
        workspace = mock.Mock(ec2={"host": "sim-host"})
        services = application_services(workspace)
        services.hardware.load.return_value = {}
        environment = services.simulation_environments.for_workspace.return_value
        environment.diag.return_value = SimulationDiagnostic(
            processes=[{"pid": 123, "cmd": "bridge.py"}],
            devices={"/dev/i2c-1": True},
            api={"ready": True},
            ok=True,
        )

        outcome = dispatch(
            SIM_RUNTIME_DIAG,
            workspace_selector="Local/Product",
            services=services,
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            render_outcome(SIM_RUNTIME_DIAG, outcome, json_output=True)

        self.assertEqual("sim-host", json.loads(output.getvalue())["host"])
        environment.diag.assert_called_once_with({})

    def test_status_checks_runtime_even_when_session_is_stopped(self) -> None:
        workspace = mock.Mock()
        services = application_services(workspace)
        services.hardware.load.return_value = {}
        environment = services.simulation_environments.for_workspace.return_value
        environment.runtime_host = "sim-host"
        environment.status.return_value = 0
        services.simulation_sessions.status.return_value = 1

        outcome = dispatch(
            SIM_RUNTIME_STATUS,
            workspace_selector="Local/Product",
            services=services,
        )

        self.assertEqual(1, outcome.exit_code)
        environment.status.assert_called_once_with({})

    def test_start_can_skip_session_management(self) -> None:
        workspace = mock.Mock()
        services = application_services(workspace)
        services.hardware.load.return_value = {}
        environment = services.simulation_environments.for_workspace.return_value
        environment.runtime_host = "sim-host"
        environment.start.return_value = 0

        outcome = dispatch(
            SIM_RUNTIME_START,
            workspace_selector="Local/Product",
            services=services,
            manage_session=False,
        )

        self.assertEqual(0, outcome.exit_code)
        services.simulation_sessions.start.assert_not_called()

    def test_wokwi_lifecycle_does_not_use_terminal_or_session(self) -> None:
        workspace = mock.Mock()
        services = application_services(workspace)
        services.hardware.load.return_value = {}
        environment = services.simulation_environments.for_workspace.return_value
        environment.runtime_host = None
        environment.start.return_value = 0

        outcome = dispatch(
            SIM_RUNTIME_START,
            workspace_selector="Local/WokwiProduct",
            services=services,
        )

        self.assertEqual(0, outcome.exit_code)
        services.simulation_sessions.configure_terminal.assert_not_called()
        services.simulation_sessions.start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
