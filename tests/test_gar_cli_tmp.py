from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path
from unittest import mock

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

    def test_sim_build_constructs_services_and_calls_dispatch(self) -> None:
        artifact = mock.Mock(bundle_path=Path("/tmp/sim-artifact"))
        with (
            mock.patch("scripts.gar_lib.cli_tmp.LocalArtifactStore") as artifact_store_type,
            mock.patch("scripts.gar_lib.cli_tmp.ConfigWorkspaceRegistry") as workspace_registry_type,
            mock.patch("scripts.gar_lib.cli_tmp.ConfigBuildEnvironmentResolver") as build_resolver_type,
            mock.patch("scripts.gar_lib.cli_tmp.ConfigSimulationEnvironmentResolver") as sim_resolver_type,
            mock.patch("scripts.gar_lib.cli_tmp.ConfigTargetEnvironmentResolver") as target_resolver_type,
            mock.patch(
                "scripts.gar_lib.cli_tmp.dispatch_sim_command",
                return_value=artifact,
            ) as dispatch,
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(["sim", "build", "--workspace", "Local/GarStreamTx"])

        self.assertEqual(0, result)
        build_resolver_type.assert_called_once_with(artifact_store_type.return_value)
        dispatch.assert_called_once()
        self.assertEqual(SIM_BUILD, dispatch.call_args.args[0])
        self.assertEqual("Local/GarStreamTx", dispatch.call_args.kwargs["workspace_selector"])
        services = dispatch.call_args.kwargs["services"]
        self.assertIs(workspace_registry_type.return_value, services.workspaces)
        self.assertIs(build_resolver_type.return_value, services.build_environments)
        self.assertIs(artifact_store_type.return_value, services.artifacts)
        self.assertIs(sim_resolver_type.return_value, services.simulation_environments)
        target_resolver_type.assert_not_called()
        self.assertIn("/tmp/sim-artifact", output.getvalue())

    def test_sim_runtime_deploy_calls_same_dispatch_with_runtime_command(self) -> None:
        with mock.patch(
            "scripts.gar_lib.cli_tmp.dispatch_sim_command",
            return_value=None,
        ) as dispatch:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(["sim", "env", "deploy", "--workspace", "Local/GarStreamRx"])

        self.assertEqual(0, result)
        self.assertEqual(SIM_RUNTIME_DEPLOY, dispatch.call_args.args[0])
        self.assertEqual("Local/GarStreamRx", dispatch.call_args.kwargs["workspace_selector"])
        self.assertIn("runtime artifactは不要", output.getvalue())

    def test_target_deploy_constructs_services_and_calls_target_dispatch(self) -> None:
        artifact = mock.Mock(bundle_path=Path("/tmp/target-artifact"))
        with (
            mock.patch("scripts.gar_lib.cli_tmp.ConfigTargetEnvironmentResolver") as resolver_type,
            mock.patch(
                "scripts.gar_lib.cli_tmp.dispatch_target_command",
                return_value=artifact,
            ) as dispatch,
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(["target", "deploy", "--workspace", "Network/GarStreamTx"])

        self.assertEqual(0, result)
        self.assertEqual(TARGET_DEPLOY, dispatch.call_args.args[0])
        self.assertEqual("Network/GarStreamTx", dispatch.call_args.kwargs["workspace_selector"])
        services = dispatch.call_args.kwargs["services"]
        self.assertIs(resolver_type.return_value, services.target_environments)
        self.assertIn("/tmp/target-artifact", output.getvalue())


if __name__ == "__main__":
    unittest.main()
