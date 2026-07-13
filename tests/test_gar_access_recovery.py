from __future__ import annotations

import unittest
from unittest import mock

from scripts.gar_lib.core.errors import AccessConnectionError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.recovery.access import AccessRecoveryPlanner, RecoveryAction
from scripts.gar_lib.recovery.terminal import TerminalBridgeRecoveryExecutor


class GarAccessRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Workspace(
            id="ws",
            name="Local/Product",
            branch="Product",
            connection={"type": "local", "path": "/tmp/product"},
            ec2={"region": "ap-northeast-1"},
        )

    def test_ssh_failure_plans_aws_login_outside_channel(self) -> None:
        error = AccessConnectionError(
            channel="ssh",
            endpoint="sim-host",
            reason="connection_or_authentication",
            returncode=255,
        )

        action = AccessRecoveryPlanner().plan(
            error,
            workspace=self.workspace,
            retry_command="gar sim deploy --workspace Local/Product",
        )

        self.assertEqual(
            ("aws", "login", "--remote", "--region", "ap-northeast-1"),
            action.terminal_command,
        )
        self.assertTrue(any("gar sim start" in instruction for instruction in action.instructions))

    def test_adb_failure_does_not_request_cloud_login(self) -> None:
        error = AccessConnectionError(
            channel="adb",
            endpoint="device-1",
            reason="device_offline",
            returncode=1,
        )

        action = AccessRecoveryPlanner().plan(error, workspace=self.workspace, retry_command="gar sim deploy")

        self.assertIsNone(action.terminal_command)
        self.assertTrue(any("gar usb attach" in instruction for instruction in action.instructions))

    def test_aws_authentication_failure_requests_visible_login(self) -> None:
        error = AccessConnectionError(
            channel="aws",
            endpoint="ap-northeast-1",
            reason="authentication",
            returncode=255,
        )

        action = AccessRecoveryPlanner().plan(
            error,
            workspace=self.workspace,
            retry_command="gar sim start --workspace Local/Product",
        )

        self.assertEqual(
            ("aws", "login", "--remote", "--region", "ap-northeast-1"),
            action.terminal_command,
        )
        self.assertTrue(any("gar sim start" in instruction for instruction in action.instructions))

    def test_terminal_executor_receives_planned_command_by_injection(self) -> None:
        requester = mock.Mock(return_value=0)
        action = RecoveryAction(
            title="AWS login",
            terminal_command=("aws", "login", "--remote", "--region", "ap-northeast-1"),
            instructions=(),
        )

        created = TerminalBridgeRecoveryExecutor(requester).execute(action)

        self.assertTrue(created)
        requester.assert_called_once()
        self.assertEqual(
            "aws login --remote --region ap-northeast-1",
            requester.call_args.kwargs["command_text"],
        )
