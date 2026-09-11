from __future__ import annotations

import contextlib
import json
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

from scripts.gar_lib.access.channel import AccessResult
from scripts.gar_lib.access.docker import (
    DockerCliChannel,
    DockerCommandChannel,
    DockerFileChannel,
)
from scripts.gar_lib.core.errors import AccessConnectionError, GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.simulation.composition import (
    hardware_control_for,
    simulation_environment_for,
    simulation_host_for,
)
from scripts.gar_lib.simulation.hardware.control import LinuxBridgeHardwareControl
from scripts.gar_lib.simulation.host.docker import (
    ABSENT_STATE,
    DockerSimulationHostController,
)
from scripts.gar_lib.simulation.host.docker_spec import DockerHostSpec, docker_host_spec
from scripts.gar_lib.simulation.runtime.linux_systemd import LinuxSystemdSimulationEnvironment
from scripts.gar_lib.target.manifest import TargetManifest

LINUX_DEVICE_DOCKER = {
    "image": "gar-linux-device:latest",
    "buildContext": "targets/linux-device",
    "publishedBridgePort": 8080,
    "containerBridgePort": 8080,
    "publishedHost": "127.0.0.1",
    "init": ["/sbin/init"],
    "privileged": True,
    "hostCgroups": True,
    "environment": ["GAR_BRIDGE_HOST=0.0.0.0"],
    "tmpfs": ["/run", "/run/lock"],
    "mounts": ["/sys/fs/cgroup:/sys/fs/cgroup:rw", "/sys/kernel/config:/sys/kernel/config"],
    "devices": ["/dev/fuse", "/dev/cuse"],
}


def inspected_container(
    spec: DockerHostSpec,
    *,
    state: str = "running",
    image: str | None = None,
    published_port: int | None = None,
    container_port: int | None = None,
    fingerprint: str | None = None,
) -> AccessResult:
    document = {
        "State": {"Status": state},
        "Config": {
            "Image": image or spec.image,
            "Labels": {"io.gapless-agent-runtime.simulation-host-spec": (fingerprint or spec.fingerprint)},
        },
        "HostConfig": {
            "PortBindings": {
                f"{container_port or spec.container_bridge_port}/tcp": [
                    {
                        "HostIp": spec.published_host,
                        "HostPort": str(published_port or spec.published_bridge_port),
                    }
                ]
            }
        },
    }
    return AccessResult(("docker",), 0, json.dumps(document), "")


def linux_device_manifest() -> TargetManifest:
    return TargetManifest(
        id="linux-device",
        display_name="Linux device",
        description="linux device",
        tools_root="targets/linux-device",
        default_backends={"simulator": "local_docker"},
        backend_notes={},
        simulation={"docker": dict(LINUX_DEVICE_DOCKER)},
    )


@contextlib.contextmanager
def target_manifest(manifest: TargetManifest | None) -> Iterator[None]:
    """container の形を決める target 定義を差し替える。"""

    with mock.patch(
        "scripts.gar_lib.simulation.composition.discover_target_manifests",
        return_value=[manifest] if manifest is not None else [],
    ):
        yield


def docker_workspace(**docker: object) -> Workspace:
    return Workspace(
        id="ws",
        name="Local/Product",
        branch="Product",
        connection={"type": "local", "path": "/tmp/product"},
        selected_environments={"simulator": "local_docker"},
        selected_target="linux-device",
        docker=docker,
    )


class DockerAccessChannelTest(unittest.TestCase):
    def test_command_channel_wraps_shell_command_for_container(self) -> None:
        completed = mock.Mock(returncode=0, stdout="ok", stderr="")
        with (
            mock.patch("scripts.gar_lib.access.docker.shutil.which", return_value="/usr/bin/docker"),
            mock.patch("scripts.gar_lib.access.docker.subprocess.run", return_value=completed) as run,
        ):
            result = DockerCommandChannel("gar-sim").run("systemctl is-active gar-bridge")

        self.assertEqual(0, result.returncode)
        self.assertEqual(
            (
                "/usr/bin/docker",
                "exec",
                "-i",
                "gar-sim",
                "bash",
                "-lc",
                "systemctl is-active gar-bridge",
            ),
            run.call_args.args[0],
        )

    def test_command_channel_reports_stopped_container_as_connection_failure(self) -> None:
        completed = mock.Mock(
            returncode=125,
            stdout="",
            stderr="Error response from daemon: Container gar-sim is not running",
        )
        with (
            mock.patch("scripts.gar_lib.access.docker.shutil.which", return_value="/usr/bin/docker"),
            mock.patch("scripts.gar_lib.access.docker.subprocess.run", return_value=completed),
        ):
            with self.assertRaises(AccessConnectionError) as raised:
                DockerCommandChannel("gar-sim").run("true")

        self.assertEqual("docker", raised.exception.channel)
        self.assertEqual("gar-sim", raised.exception.endpoint)
        self.assertEqual("container", raised.exception.reason)

    def test_cli_channel_reports_stopped_daemon_as_connection_failure(self) -> None:
        completed = mock.Mock(
            returncode=1,
            stdout="",
            stderr="Cannot connect to the Docker daemon at unix:///var/run/docker.sock.",
        )
        with (
            mock.patch("scripts.gar_lib.access.docker.shutil.which", return_value="/usr/bin/docker"),
            mock.patch("scripts.gar_lib.access.docker.subprocess.run", return_value=completed),
        ):
            with self.assertRaises(AccessConnectionError) as raised:
                DockerCliChannel().run(("ps",))

        self.assertEqual("daemon", raised.exception.reason)

    def test_missing_docker_executable_is_a_domain_error(self) -> None:
        with mock.patch("scripts.gar_lib.access.docker.shutil.which", return_value=None):
            with self.assertRaisesRegex(GarDomainError, "docker"):
                DockerCliChannel().run(("ps",))

    def test_file_channel_pushes_through_docker_cp(self) -> None:
        completed = mock.Mock(returncode=0, stdout="", stderr="")
        with (
            mock.patch("scripts.gar_lib.access.docker.shutil.which", return_value="/usr/bin/docker"),
            mock.patch("scripts.gar_lib.access.docker.subprocess.run", return_value=completed) as run,
        ):
            DockerFileChannel("gar-sim").push(Path("/tmp/bundle"), "/tmp/staged")

        self.assertEqual(
            ("/usr/bin/docker", "cp", str(Path("/tmp/bundle")), "gar-sim:/tmp/staged"),
            run.call_args.args[0],
        )


class DockerSimulationHostControllerTest(unittest.TestCase):
    def controller(self, docker: mock.Mock) -> DockerSimulationHostController:
        return DockerSimulationHostController(
            container="gar-sim",
            spec=docker_host_spec(LINUX_DEVICE_DOCKER),
            docker=docker,
            repository_channel=mock.Mock(),
        )

    def test_status_reports_absent_container_without_raising(self) -> None:
        docker = mock.Mock()
        docker.run.return_value = AccessResult(("docker",), 1, "", "Error: No such object: gar-sim")

        state = self.controller(docker).status()

        self.assertEqual(ABSENT_STATE, state.state)
        self.assertFalse(state.running)
        self.assertIsNone(state.address)
        self.assertEqual("docker", state.backend)

    def test_start_creates_container_when_absent(self) -> None:
        docker = mock.Mock()
        spec = docker_host_spec(LINUX_DEVICE_DOCKER)
        assert spec is not None
        docker.run.side_effect = [
            AccessResult(("docker",), 1, "", "No such object: gar-sim"),
            AccessResult(("docker",), 0, "sha256:abc\n"),
            AccessResult(("docker",), 0, "abc123\n"),
            inspected_container(spec),
        ]

        result = self.controller(docker).start()

        self.assertTrue(result.state.running)
        self.assertEqual("127.0.0.1", result.state.address)
        self.assertFalse(result.address_updated)
        created = docker.run.call_args_list[2].args[0]
        self.assertEqual("run", created[0])
        self.assertIn("--privileged", created)
        self.assertIn("/sys/kernel/config:/sys/kernel/config", created)
        self.assertIn("/dev/cuse", created)
        self.assertIn("GAR_BRIDGE_HOST=0.0.0.0", created)
        self.assertIn("GAR_BRIDGE_PORT=8080", created)
        self.assertIn("127.0.0.1:8080:8080", created)
        self.assertIn(
            "io.gapless-agent-runtime.simulation-host-spec=" + spec.fingerprint,
            created,
        )
        self.assertEqual("/sbin/init", created[-1])

    def test_start_builds_image_from_target_build_context_when_missing(self) -> None:
        docker = mock.Mock()
        spec = docker_host_spec(LINUX_DEVICE_DOCKER)
        assert spec is not None
        docker.run.side_effect = [
            AccessResult(("docker",), 1, "", "No such object: gar-sim"),
            AccessResult(("docker",), 1, "", "No such image"),
            AccessResult(("docker",), 0, "built\n"),
            AccessResult(("docker",), 0, "abc123\n"),
            inspected_container(spec),
        ]

        self.controller(docker).start()

        self.assertEqual(
            ("build", "--tag", "gar-linux-device:latest", "targets/linux-device"),
            docker.run.call_args_list[2].args[0],
        )

    def test_start_rebuilds_a_local_context_before_creating_container(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = root / "targets" / "linux-device"
            context.mkdir(parents=True)
            (context / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
            spec = docker_host_spec(LINUX_DEVICE_DOCKER, root=root)
            assert spec is not None
            docker = mock.Mock()
            docker.run.side_effect = [
                AccessResult(("docker",), 1, "", "No such object: gar-sim"),
                AccessResult(("docker",), 0, "built\n", ""),
                AccessResult(("docker",), 0, "container\n", ""),
                inspected_container(spec),
            ]
            controller = DockerSimulationHostController(
                container="gar-sim",
                spec=spec,
                docker=docker,
                repository_channel=mock.Mock(),
            )

            controller.start()

        self.assertEqual(
            ("build", "--tag", spec.image, spec.build_context),
            docker.run.call_args_list[1].args[0],
        )

    def test_start_publishes_host_port_to_the_distinct_container_port(self) -> None:
        docker = mock.Mock()
        spec = DockerHostSpec(
            image="gar-linux-device:latest",
            published_bridge_port=18080,
            container_bridge_port=8080,
        )
        docker.run.side_effect = [
            AccessResult(("docker",), 1, "", "No such object: gar-sim"),
            AccessResult(("docker",), 0, "sha256:abc\n"),
            AccessResult(("docker",), 0, "abc123\n"),
            inspected_container(spec),
        ]
        controller = DockerSimulationHostController(
            container="gar-sim",
            spec=spec,
            docker=docker,
            repository_channel=mock.Mock(),
        )

        controller.start()

        created = docker.run.call_args_list[2].args[0]
        self.assertIn("127.0.0.1:18080:8080", created)

    def test_start_formats_an_ipv6_published_host_for_docker(self) -> None:
        docker = mock.Mock()
        spec = DockerHostSpec(
            image="gar-linux-device:latest",
            published_bridge_port=18080,
            container_bridge_port=8080,
            published_host="::1",
        )
        docker.run.side_effect = [
            AccessResult(("docker",), 1, "", "No such object: gar-sim"),
            AccessResult(("docker",), 0, "sha256:abc\n"),
            AccessResult(("docker",), 0, "abc123\n"),
            inspected_container(spec),
        ]
        controller = DockerSimulationHostController(
            container="gar-sim",
            spec=spec,
            docker=docker,
            repository_channel=mock.Mock(),
        )

        controller.start()

        created = docker.run.call_args_list[2].args[0]
        self.assertIn("[::1]:18080:8080", created)

    def test_start_requires_a_build_context_when_image_is_missing(self) -> None:
        docker = mock.Mock()
        docker.run.side_effect = [
            AccessResult(("docker",), 1, "", "No such object: gar-sim"),
            AccessResult(("docker",), 1, "", "No such image"),
        ]
        controller = DockerSimulationHostController(
            container="gar-sim",
            spec=DockerHostSpec(image="missing:latest"),
            docker=docker,
            repository_channel=mock.Mock(),
        )

        with self.assertRaisesRegex(GarDomainError, "missing:latest"):
            controller.start()

    def test_start_restarts_existing_stopped_container(self) -> None:
        docker = mock.Mock()
        spec = docker_host_spec(LINUX_DEVICE_DOCKER)
        assert spec is not None
        docker.run.side_effect = [
            inspected_container(spec, state="exited"),
            AccessResult(("docker",), 0, "gar-sim\n"),
            inspected_container(spec),
        ]

        result = self.controller(docker).start()

        self.assertTrue(result.state.running)
        self.assertEqual(("start", "gar-sim"), docker.run.call_args_list[1].args[0])

    def test_status_reports_actual_image_and_port_binding_with_drift(self) -> None:
        docker = mock.Mock()
        spec = docker_host_spec(LINUX_DEVICE_DOCKER)
        assert spec is not None
        docker.run.return_value = inspected_container(
            spec,
            image="gar-linux-device:old",
            published_port=18080,
            fingerprint="old-fingerprint",
        )

        state = self.controller(docker).status()

        self.assertEqual("gar-linux-device:old", state.details["image"])
        self.assertEqual("127.0.0.1:18080->8080/tcp", state.details["port_bindings"])
        self.assertEqual("false", state.details["spec_matches"])
        self.assertIn("image=", state.details["spec_drift"])
        self.assertIn("bridge port=", state.details["spec_drift"])

    def test_start_rejects_existing_container_with_old_spec(self) -> None:
        docker = mock.Mock()
        spec = docker_host_spec(LINUX_DEVICE_DOCKER)
        assert spec is not None
        docker.run.return_value = inspected_container(
            spec,
            image="gar-linux-device:old",
            fingerprint="old-fingerprint",
        )

        with self.assertRaisesRegex(GarDomainError, "docker rm -f gar-sim"):
            self.controller(docker).start()

        self.assertEqual(1, docker.run.call_count)

    def test_stop_rejects_absent_container(self) -> None:
        docker = mock.Mock()
        docker.run.return_value = AccessResult(("docker",), 1, "", "No such object: gar-sim")

        with self.assertRaisesRegex(GarDomainError, "gar-sim"):
            self.controller(docker).stop()


class DockerBackendTest(unittest.TestCase):
    def test_build_context_content_changes_the_spec_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = root / "targets" / "linux-device"
            context.mkdir(parents=True)
            dockerfile = context / "Dockerfile"
            dockerfile.write_text("FROM scratch\n", encoding="utf-8")
            first = docker_host_spec(LINUX_DEVICE_DOCKER, root=root)

            dockerfile.write_text("FROM scratch\nLABEL revision=2\n", encoding="utf-8")
            second = docker_host_spec(LINUX_DEVICE_DOCKER, root=root)

        assert first is not None and second is not None
        self.assertNotEqual(first.build_context_fingerprint, second.build_context_fingerprint)
        self.assertNotEqual(first.fingerprint, second.fingerprint)

    def test_build_context_dependency_changes_the_spec_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = root / "targets" / "linux-device"
            requirements = context / "runtime" / "web-bridge" / "requirements.txt"
            requirements.parent.mkdir(parents=True)
            (context / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
            requirements.write_text("aiohttp==3.14.1\n", encoding="utf-8")
            first = docker_host_spec(LINUX_DEVICE_DOCKER, root=root)

            requirements.write_text("aiohttp==3.14.2\n", encoding="utf-8")
            second = docker_host_spec(LINUX_DEVICE_DOCKER, root=root)

        assert first is not None and second is not None
        self.assertNotEqual(first.build_context_fingerprint, second.build_context_fingerprint)
        self.assertNotEqual(first.fingerprint, second.fingerprint)

    def test_manifest_published_host_is_used_by_the_docker_spec(self) -> None:
        spec = docker_host_spec(
            {
                **LINUX_DEVICE_DOCKER,
                "publishedHost": " 127.0.0.2 ",
            }
        )

        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual("127.0.0.2", spec.published_host)

    def test_published_host_accepts_valid_ipv4_and_ipv6_addresses(self) -> None:
        for value, expected in (
            ("0.0.0.0", "0.0.0.0"),
            ("::1", "::1"),
            ("2001:0db8::1", "2001:db8::1"),
        ):
            with self.subTest(value=value):
                spec = docker_host_spec({"image": "example", "publishedHost": value})

                assert spec is not None
                self.assertEqual(expected, spec.published_host)

    def test_invalid_published_host_falls_back_to_loopback(self) -> None:
        for value in ("localhost", "127.0.0.999", "", 123):
            with self.subTest(value=value):
                spec = docker_host_spec({"image": "example", "publishedHost": value})

                assert spec is not None
                self.assertEqual("127.0.0.1", spec.published_host)

    def test_manifest_environment_is_part_of_the_docker_fingerprint(self) -> None:
        private_bridge = docker_host_spec(
            {
                **LINUX_DEVICE_DOCKER,
                "environment": ["GAR_BRIDGE_HOST=127.0.0.1"],
            }
        )
        published_bridge = docker_host_spec(
            {
                **LINUX_DEVICE_DOCKER,
                "environment": ["GAR_BRIDGE_HOST=0.0.0.0"],
            }
        )

        assert private_bridge is not None and published_bridge is not None
        self.assertIn("--env", published_bridge.run_options)
        self.assertIn("GAR_BRIDGE_HOST=0.0.0.0", published_bridge.run_options)
        self.assertNotEqual(private_bridge.fingerprint, published_bridge.fingerprint)

    def test_manifest_cannot_override_the_managed_bridge_port_environment(self) -> None:
        spec = docker_host_spec(
            {
                "image": "example",
                "containerBridgePort": 9090,
                "environment": [
                    "GAR_BRIDGE_HOST=0.0.0.0",
                    "GAR_BRIDGE_PORT=1234",
                ],
            }
        )

        assert spec is not None
        self.assertIn("GAR_BRIDGE_HOST=0.0.0.0", spec.run_options)
        self.assertNotIn("GAR_BRIDGE_PORT=1234", spec.run_options)
        self.assertEqual(9090, spec.container_bridge_port)

    def test_manifest_distinguishes_published_and_container_bridge_ports(self) -> None:
        settings = {
            **LINUX_DEVICE_DOCKER,
            "publishedBridgePort": 18080,
            "containerBridgePort": 8080,
        }

        spec = docker_host_spec(settings)

        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(18080, spec.published_bridge_port)
        self.assertEqual(8080, spec.container_bridge_port)

    def test_legacy_bridge_port_applies_to_both_sides(self) -> None:
        spec = docker_host_spec({"image": "example", "bridgePort": 9090})

        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(9090, spec.published_bridge_port)
        self.assertEqual(9090, spec.container_bridge_port)

    def test_host_takes_container_shape_from_target_definition(self) -> None:
        with target_manifest(linux_device_manifest()):
            controller = simulation_host_for(docker_workspace())

        self.assertIsInstance(controller, DockerSimulationHostController)
        self.assertEqual("gar-sim", controller.container)
        self.assertEqual("gar-linux-device:latest", controller.image)
        self.assertIn("--device", controller.spec.run_options)
        self.assertIn("/dev/cuse", controller.spec.run_options)
        self.assertEqual(("/sbin/init",), controller.spec.init_command)
        self.assertEqual(("targets", "linux-device"), Path(controller.spec.build_context).parts[-2:])

    def test_host_honours_workspace_docker_settings(self) -> None:
        workspace = docker_workspace(container="poc", image="poc:dev", bridge_port=9090)

        with target_manifest(linux_device_manifest()):
            controller = simulation_host_for(workspace)

        self.assertEqual("poc", controller.container)
        self.assertEqual("poc:dev", controller.image)
        self.assertEqual(9090, controller.bridge_port)
        self.assertEqual(8080, controller.spec.container_bridge_port)
        self.assertIn("--privileged", controller.spec.run_options)

    def test_workspace_port_overrides_only_the_published_port(self) -> None:
        manifest = linux_device_manifest()
        manifest.simulation["docker"].update({"publishedBridgePort": 18080, "containerBridgePort": 8080})
        workspace = docker_workspace(bridge_port=19090)

        with target_manifest(manifest):
            controller = simulation_host_for(workspace)

        self.assertEqual(19090, controller.spec.published_bridge_port)
        self.assertEqual(8080, controller.spec.container_bridge_port)

    def test_host_requires_an_image_when_target_is_unknown(self) -> None:
        with target_manifest(None), self.assertRaisesRegex(GarDomainError, "image"):
            simulation_host_for(docker_workspace())

    def test_host_falls_back_to_workspace_image_without_target(self) -> None:
        with target_manifest(None):
            controller = simulation_host_for(docker_workspace(image="poc:dev"))

        self.assertEqual("poc:dev", controller.image)
        self.assertEqual((), controller.spec.run_options)

    def test_environment_reuses_linux_systemd_runtime(self) -> None:
        environment = simulation_environment_for(docker_workspace())

        self.assertIsInstance(environment, LinuxSystemdSimulationEnvironment)
        self.assertIsInstance(environment.command_channel, DockerCommandChannel)
        self.assertIsInstance(environment.file_channel, DockerFileChannel)
        self.assertIsNone(environment.session_host)

    def test_hardware_control_reuses_linux_bridge(self) -> None:
        control = hardware_control_for(docker_workspace())

        self.assertIsInstance(control, LinuxBridgeHardwareControl)
        self.assertIsInstance(control.command_channel, DockerCommandChannel)


if __name__ == "__main__":
    unittest.main()
