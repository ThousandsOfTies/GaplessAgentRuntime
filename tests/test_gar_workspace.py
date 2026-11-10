from __future__ import annotations

import unittest

from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.core.workspace_settings import (
    BuildSettings,
    DockerSettings,
    Ec2Settings,
    SelectedEnvironments,
    SimulationHostSettings,
    VirtualBoxSettings,
    WorkspaceConnection,
)


class WorkspaceSettingsTest(unittest.TestCase):
    def test_json_mappings_are_converted_at_the_workspace_boundary(self) -> None:
        workspace = Workspace(
            id="ws_typed",
            name="Local/Typed",
            branch="Typed",
            connection={"type": "local", "path": "/tmp/typed"},
            selected_environments={
                "codespace": "local",
                "simulator": "ssh_remote",
                "simulation_host": "virtualbox",
                "target": "ssh_scp",
            },
            build={"image": "gar-build:test", "docker_socket": False},
            simulation_host={
                "provider": "virtualbox",
                "host": "gar-sim-local",
                "private_ip": "192.0.2.10",
                "arch": "x86_64",
                "repo_dir": "/srv/gar",
                "bridge_port": 8181,
            },
            virtualbox={"vm": "GAR Ubuntu Sim"},
            ec2={"host": "sim-host", "private_ip": "10.0.1.25", "region": "ap-test-1"},
            docker={"container": "gar-sim", "bridge_port": 9090},
        )

        self.assertIsInstance(workspace.connection, WorkspaceConnection)
        self.assertIsInstance(workspace.selected_environments, SelectedEnvironments)
        self.assertIsInstance(workspace.build, BuildSettings)
        self.assertIsInstance(workspace.simulation_host, SimulationHostSettings)
        self.assertIsInstance(workspace.virtualbox, VirtualBoxSettings)
        self.assertIsInstance(workspace.ec2, Ec2Settings)
        self.assertIsInstance(workspace.docker, DockerSettings)
        self.assertEqual("ssh_remote", workspace.selected_environments.simulator)
        self.assertEqual("virtualbox", workspace.selected_environments.simulation_host)
        self.assertEqual("gar-build:test", workspace.build.image)
        self.assertFalse(workspace.build.docker_socket)
        self.assertEqual("gar-sim-local", workspace.simulation_host.host)
        self.assertEqual("192.0.2.10", workspace.simulation_host.private_ip)
        self.assertEqual("x86_64", workspace.simulation_host.arch)
        self.assertEqual(8181, workspace.simulation_host.bridge_port)
        self.assertEqual("GAR Ubuntu Sim", workspace.virtualbox.vm)
        self.assertEqual("sim-host", workspace.ec2.host)
        self.assertEqual("10.0.1.25", workspace.ec2.private_ip)
        self.assertEqual(9090, workspace.docker.bridge_port)

    def test_build_does_not_expose_the_docker_daemon_by_default(self) -> None:
        self.assertFalse(BuildSettings.from_value({}).docker_socket)

    def test_build_cache_requires_an_explicit_boolean_opt_in(self) -> None:
        self.assertFalse(BuildSettings.from_value({}).cache)
        self.assertTrue(BuildSettings.from_value({"cache": True}).cache)
        self.assertFalse(BuildSettings.from_value({"cache": False}).cache)
        for invalid in (None, "true", "false", 1, 0, [], {}):
            with self.subTest(value=invalid):
                self.assertFalse(BuildSettings.from_value({"cache": invalid}).cache)

    def test_typed_settings_keep_mapping_compatibility_at_legacy_boundaries(self) -> None:
        settings = DockerSettings(container="gar-sim", bridge_port=8080)

        self.assertEqual("gar-sim", settings.get("container"))
        self.assertEqual(8080, settings["bridge_port"])
        self.assertEqual(
            {"container": "gar-sim", "bridge_port": 8080},
            settings.to_dict(),
        )

    def test_virtualbox_and_aws_default_to_their_host_architectures(self) -> None:
        virtualbox = Workspace(
            id="ws-vbox",
            name="Local/VBox",
            branch="VBox",
            connection={"type": "local", "path": "/tmp/vbox"},
            selected_environments={
                "simulator": "ssh_remote",
                "simulation_host": "virtualbox",
            },
            simulation_host={"host": "gar-sim-local"},
            virtualbox={"vm": "GAR Ubuntu Sim"},
        )
        aws = Workspace(
            id="ws-aws",
            name="Local/AWS",
            branch="AWS",
            connection={"type": "local", "path": "/tmp/aws"},
            selected_environments={
                "simulator": "ssh_remote",
                "simulation_host": "aws_ec2",
            },
            simulation_host={"host": "gar-sim-aws"},
        )

        self.assertEqual("x86_64", virtualbox.simulation_architecture)
        self.assertEqual("aarch64", aws.simulation_architecture)

    def test_explicit_simulation_host_architecture_overrides_provider_default(self) -> None:
        workspace = Workspace(
            id="ws-custom",
            name="Local/Custom",
            branch="Custom",
            connection={"type": "local", "path": "/tmp/custom"},
            selected_environments={
                "simulator": "ssh_remote",
                "simulation_host": "virtualbox",
            },
            simulation_host={"host": "sim", "arch": "aarch64"},
            virtualbox={"vm": "GAR Ubuntu Sim"},
        )

        self.assertEqual("aarch64", workspace.simulation_architecture)

    def test_virtualbox_selection_ignores_stale_aws_host_values(self) -> None:
        workspace = Workspace(
            id="ws-switched",
            name="Local/Switched",
            branch="Switched",
            connection={"type": "local", "path": "/tmp/switched"},
            selected_environments={
                "simulator": "ssh_remote",
                "simulation_host": "virtualbox",
            },
            simulation_host={
                "provider": "aws_ec2",
                "host": "stale-aws",
                "private_ip": "10.0.0.10",
                "arch": "aarch64",
                "bridge_port": 9090,
            },
            virtualbox={"vm": "GAR Ubuntu Sim"},
            ec2={"host": "legacy-aws", "private_ip": "10.0.0.20", "arch": "aarch64"},
        )

        self.assertIsNone(workspace.simulation_ssh_host)
        self.assertIsNone(workspace.simulation_private_ip)
        self.assertIsNone(workspace.simulation_bridge_port)
        self.assertEqual("x86_64", workspace.simulation_architecture)


if __name__ == "__main__":
    unittest.main()
