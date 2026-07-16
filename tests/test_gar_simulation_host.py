from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.gar_lib.access.aws import AwsCliChannel
from scripts.gar_lib.access.base import CommandResult
from scripts.gar_lib.simulation.ssh_config import SshConfigHostAddressUpdater
from scripts.gar_lib.core.errors import AccessConnectionError, GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.simulation.aws_ec2 import AwsEc2SimulationHostController
from scripts.gar_lib.simulation.host_resolver import ConfigSimulationHostControllerResolver


class GarSimulationHostTest(unittest.TestCase):
    def test_aws_channel_classifies_expired_session_without_host_decisions(self) -> None:
        completed = mock.Mock(
            returncode=255,
            stdout="",
            stderr="Your session has expired. Please reauthenticate using 'aws login'.",
        )
        with (
            mock.patch("scripts.gar_lib.access.aws.shutil.which", return_value="/usr/bin/aws"),
            mock.patch("scripts.gar_lib.access.aws.subprocess.run", return_value=completed),
        ):
            with self.assertRaises(AccessConnectionError) as raised:
                AwsCliChannel("ap-northeast-1").run(("ec2", "describe-instances"))

        self.assertEqual("aws", raised.exception.channel)
        self.assertEqual("authentication", raised.exception.reason)

    def test_ssh_config_updater_only_manages_host_address(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config"
            path.write_text(
                "Host sim-host\n    User ubuntu\n\nHost another-host\n    HostName old\n",
                encoding="utf-8",
            )

            updated = SshConfigHostAddressUpdater(path).update("sim-host", "203.0.113.5")

            self.assertTrue(updated)
            contents = path.read_text(encoding="utf-8")
            self.assertIn("Host sim-host\n    HostName 203.0.113.5\n    User ubuntu", contents)
            self.assertIn("Host another-host\n    HostName old", contents)

    def test_ec2_controller_composes_aws_ssh_config_and_repository_channels(self) -> None:
        aws = mock.Mock()
        aws.run.side_effect = [
            CommandResult(("aws",), 0),
            CommandResult(("aws",), 0),
            CommandResult(("aws",), 0, "running\n"),
            CommandResult(("aws",), 0, "203.0.113.5\n"),
        ]
        address_updater = mock.Mock()
        address_updater.update.return_value = True
        repository = mock.Mock()
        repository.run.return_value = CommandResult(("ssh",), 0)
        controller = AwsEc2SimulationHostController(
            host="sim-host",
            instance_id="i-test",
            region="ap-northeast-1",
            aws=aws,
            address_updater=address_updater,
            repository_channel=repository,
            repository_path="/srv/simulation repo",
        )

        result = controller.start(update_address=True, update_repository=True)

        self.assertTrue(result.state.running)
        self.assertEqual("203.0.113.5", result.state.public_ip)
        self.assertTrue(result.address_updated)
        self.assertTrue(result.repository_updated)
        address_updater.update.assert_called_once_with("sim-host", "203.0.113.5")
        repository.run.assert_called_once_with("cd '/srv/simulation repo' && git pull --ff-only")
        self.assertIn("start-instances", aws.run.call_args_list[0].args[0])
        self.assertIn("instance-running", aws.run.call_args_list[1].args[0])

    def test_ec2_controller_reports_non_authentication_aws_failure_as_domain_error(self) -> None:
        aws = mock.Mock()
        aws.run.return_value = CommandResult(("aws",), 2, "", "access denied")
        controller = AwsEc2SimulationHostController(
            host="sim-host",
            instance_id="i-test",
            region="ap-northeast-1",
            aws=aws,
            address_updater=mock.Mock(),
            repository_channel=mock.Mock(),
        )

        with self.assertRaises(GarDomainError):
            controller.stop()

    def test_resolver_builds_controller_from_workspace_ec2_settings(self) -> None:
        workspace = Workspace(
            id="ws",
            name="Local/Product",
            branch="Product",
            connection={"type": "local", "path": "/tmp/product"},
            ec2={
                "host": "sim-host",
                "instance_id": "i-test",
                "region": "ap-northeast-1",
            },
        )

        controller = ConfigSimulationHostControllerResolver().for_workspace(workspace)

        self.assertIsInstance(controller, AwsEc2SimulationHostController)
        self.assertEqual("i-test", controller.instance_id)

    def test_resolver_rejects_incomplete_host_configuration(self) -> None:
        workspace = Workspace(
            id="ws",
            name="Local/Product",
            branch="Product",
            connection={"type": "local", "path": "/tmp/product"},
            ec2={"host": "sim-host"},
        )

        with self.assertRaisesRegex(GarDomainError, "instance_id, region"):
            ConfigSimulationHostControllerResolver().for_workspace(workspace)
