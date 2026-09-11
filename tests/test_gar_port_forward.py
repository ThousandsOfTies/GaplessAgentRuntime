from __future__ import annotations

import contextlib
import io
import signal
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from tools import forward_sim_ports as forward_ec2_ports


def state_for(config: forward_ec2_ports.PortForwardConfig) -> forward_ec2_ports.PortForwardState:
    command = config.ssh_command("/usr/bin/ssh", Path("/home/test/.ssh/config"))
    return forward_ec2_ports.PortForwardState(
        pid=4321,
        config=config,
        command=command,
        started_at=datetime.now(UTC).isoformat(),
    )


class PortForwardStateTest(unittest.TestCase):
    def test_legacy_ec2_state_is_migrated_to_generic_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            legacy = forward_ec2_ports.PortForwardStateStore(root / "ec2-port-forward.json")
            current = forward_ec2_ports.PortForwardStateStore(root / "sim-port-forward.json")
            expected = state_for(forward_ec2_ports.PortForwardConfig("host-a", 8080))
            legacy.save(expected)

            forward_ec2_ports.migrate_legacy_state_file(
                legacy_state_path=legacy.state_path,
                store=current,
            )

            self.assertEqual(expected, current.load())
            self.assertFalse(legacy.state_path.exists())

    def test_ssh_command_forwards_panel_http_and_websocket_on_one_port(self) -> None:
        command = forward_ec2_ports.PortForwardConfig("host-a", 8080).ssh_command(
            "/usr/bin/ssh",
            Path("/home/test/.ssh/config"),
        )

        self.assertEqual(1, command.count("-L"))
        self.assertIn("8080:127.0.0.1:8080", command)
        self.assertIn("StrictHostKeyChecking=accept-new", command)
        self.assertIn("HostKeyAlias=host-a", command)

    def test_state_reader_accepts_legacy_ws_port_field(self) -> None:
        payload = state_for(forward_ec2_ports.PortForwardConfig("host-a", 8080)).to_payload()
        payload["ws_port"] = 8765

        state = forward_ec2_ports.PortForwardState.from_payload(payload)

        self.assertEqual(forward_ec2_ports.PortForwardConfig("host-a", 8080), state.config)

    def test_legacy_two_port_process_can_be_adopted_and_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            legacy_pid_path = root / "port-forward.pid"
            legacy_pid_path.write_text("4321\n", encoding="utf-8")
            store = forward_ec2_ports.PortForwardStateStore(root / "port-forward.json")
            config = forward_ec2_ports.PortForwardConfig("host-a", 8080)
            current_command = config.ssh_command("/usr/bin/ssh", Path("/home/test/.ssh/config"))
            legacy_command = config.legacy_ssh_command(
                "/usr/bin/ssh",
                Path("/home/test/.ssh/config"),
            )

            with mock.patch.object(
                forward_ec2_ports,
                "read_process_command",
                return_value=legacy_command,
            ):
                state = forward_ec2_ports.migrate_legacy_pid_file(
                    legacy_pid_path=legacy_pid_path,
                    store=store,
                    config=config,
                    expected_command=current_command,
                    alternative_commands=(legacy_command,),
                )

            self.assertIsNotNone(state)
            self.assertEqual(legacy_command, state.command)
            self.assertFalse(legacy_pid_path.exists())
            self.assertTrue(store.state_path.exists())

    def test_parser_requires_host_when_ec2_environment_is_unset(self) -> None:
        with (
            mock.patch.dict(forward_ec2_ports.os.environ, {}, clear=True),
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            forward_ec2_ports.build_parser().parse_args([])

    def test_parser_uses_explicit_ec2_environment_host(self) -> None:
        with mock.patch.dict(forward_ec2_ports.os.environ, {"EC2": "configured-host"}, clear=True):
            args = forward_ec2_ports.build_parser().parse_args([])

        self.assertEqual("configured-host", args.host)

    def test_parser_prefers_generic_sim_host_environment(self) -> None:
        with mock.patch.dict(
            forward_ec2_ports.os.environ,
            {"GAR_SIM_HOST": "local-sim", "EC2": "legacy-aws"},
            clear=True,
        ):
            args = forward_ec2_ports.build_parser().parse_args([])

        self.assertEqual("local-sim", args.host)

    def test_command_identity_allows_only_executable_path_to_differ(self) -> None:
        expected = ("/usr/bin/ssh", "-N", "example-host")

        self.assertTrue(
            forward_ec2_ports.commands_identify_same_process(
                expected,
                ("ssh", "-N", "example-host"),
            )
        )
        self.assertFalse(
            forward_ec2_ports.commands_identify_same_process(
                expected,
                ("ssh", "-N", "another-host"),
            )
        )

    def test_stale_pid_is_removed_without_signalling_that_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = forward_ec2_ports.PortForwardStateStore(Path(temporary_directory) / "port-forward.json")
            config = forward_ec2_ports.PortForwardConfig("host-a", 8080)
            store.save(state_for(config))

            with (
                mock.patch.object(forward_ec2_ports, "process_is_owned", return_value=False),
                mock.patch.object(forward_ec2_ports.os, "kill") as kill,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = forward_ec2_ports.stop_forward(
                    requested_config=config,
                    store=store,
                )

            self.assertEqual(0, result)
            self.assertFalse(store.state_path.exists())
            kill.assert_not_called()

    def test_stop_refuses_to_signal_a_forward_for_another_host(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = forward_ec2_ports.PortForwardStateStore(Path(temporary_directory) / "port-forward.json")
            active_config = forward_ec2_ports.PortForwardConfig("host-a", 8080)
            requested_config = forward_ec2_ports.PortForwardConfig("host-b", 8080)
            store.save(state_for(active_config))

            with (
                mock.patch.object(forward_ec2_ports, "process_is_owned", return_value=True),
                mock.patch.object(forward_ec2_ports.os, "kill") as kill,
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                result = forward_ec2_ports.stop_forward(
                    requested_config=requested_config,
                    store=store,
                )

            self.assertEqual(1, result)
            self.assertTrue(store.state_path.exists())
            kill.assert_not_called()

    def test_stop_signals_only_the_owned_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = forward_ec2_ports.PortForwardStateStore(Path(temporary_directory) / "port-forward.json")
            config = forward_ec2_ports.PortForwardConfig("host-a", 8080)
            store.save(state_for(config))

            ownership_checks = iter((True, False))
            with (
                mock.patch.object(
                    forward_ec2_ports,
                    "process_is_owned",
                    side_effect=lambda _state: next(ownership_checks),
                ),
                mock.patch.object(forward_ec2_ports.os, "kill") as kill,
                mock.patch("psutil.Process") as process,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = forward_ec2_ports.stop_forward(
                    requested_config=config,
                    store=store,
                )

            self.assertEqual(0, result)
            if forward_ec2_ports.os.name == "nt":
                process.assert_called_once_with(4321)
                process.return_value.terminate.assert_called_once_with()
                kill.assert_not_called()
            else:
                kill.assert_called_once_with(4321, signal.SIGTERM)
                process.assert_not_called()
            self.assertFalse(store.state_path.exists())


if __name__ == "__main__":
    unittest.main()
