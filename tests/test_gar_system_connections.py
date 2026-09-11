from __future__ import annotations

import contextlib
import io
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.gar_lib.cli import main
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.output import JSON_OUTPUT
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.simulation.runtime.process import LocalProcessChannel, ManagedProcess
from scripts.gar_lib.system.connections import SystemConnections
from scripts.gar_lib.system.model import topology_from_value
from scripts.gar_lib.system.orchestrator import SystemOrchestrator


def topology():
    return topology_from_value(
        {
            "schema_version": 1,
            "name": "test",
            "order": ["tx", "rx"],
            "nodes": [
                {
                    "id": node,
                    "workspace": f"Local/{node}",
                    "app": node,
                    "role": node,
                    "environment": "sim",
                    "runtime_env": {},
                }
                for node in ("tx", "rx")
            ],
            "links": [{"id": "data", "from": "tx", "to": "rx", "protocol": "udp", "port": 5600}],
        }
    )


class SystemConnectionsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.live = set()
        self.channel = mock.Mock()
        self.channel.find_executable.return_value = "ssh"
        self.channel.owns.side_effect = lambda process: process.pid in self.live
        self.channel.terminate_group.side_effect = lambda process: self.live.discard(process.pid)

        def start(argv, **_options):
            process = ManagedProcess(100 + self.channel.start.call_count, argv, 50)
            self.live.add(process.pid)
            return process

        self.channel.start.side_effect = start
        self.resolver = mock.Mock(
            side_effect=lambda name: Workspace(
                name,
                name,
                "main",
                {"type": "local", "path": str(self.root)},
                selected_environments={"simulator": "ssh_remote"},
                ec2={"host": "example-sim"},
            )
        )
        self.manager = SystemConnections(
            self.root / "system.json", directory=self.root, channel=self.channel, resolver=self.resolver
        )
        self.ports = {"tx": 18081, "rx": 18082}

    def connect(self):
        with (
            mock.patch.object(self.manager, "_require_free"),
            mock.patch.object(self.manager, "_ready", return_value=True),
        ):
            return self.manager.connect(topology(), self.ports)

    def test_connect_reuses_owned_tunnels_and_disconnect_works_without_topology_or_workspace(self):
        self.assertTrue(self.connect()["ok"])
        self.assertEqual({"tx": "http://127.0.0.1:18081", "rx": "http://127.0.0.1:18082"}, self.manager.urls())
        self.assertTrue(self.connect()["ok"])
        self.assertEqual(2, self.channel.start.call_count)
        for call in self.channel.start.call_args_list:
            self.assertIn("ExitOnForwardFailure=yes", call.args[0])
            self.assertTrue(call.args[0][-2].startswith("127.0.0.1:"))
        self.resolver.side_effect = AssertionError("disconnect must not resolve workspaces")
        self.assertTrue(self.manager.disconnect()["ok"])
        self.assertEqual(2, self.channel.terminate_group.call_count)
        self.assertFalse(self.live)

    def test_invalid_ports_unknown_nodes_and_unsupported_backend_fail_before_processes(self):
        for ports in ({"tx": 8080, "rx": 8080}, {"tx": 0, "rx": 8081}, {"unknown": 8080}, {}):
            with self.subTest(ports=ports), self.assertRaises(GarDomainError):
                self.manager.connect(topology(), ports)
        self.resolver.side_effect = None
        self.resolver.return_value = Workspace(
            "test",
            "test",
            "main",
            {"type": "local", "path": str(self.root)},
            selected_environments={"simulator": "wokwi"},
        )
        with self.assertRaisesRegex(GarDomainError, "SSH Remote"):
            self.manager.connect(topology(), self.ports)
        self.channel.start.assert_not_called()
        self.assertFalse(self.manager.store.path.exists())

    def test_busy_external_port_is_rejected_without_adoption_or_termination(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            ports = {**self.ports, "tx": listener.getsockname()[1]}
            with self.assertRaisesRegex(GarDomainError, "使用中"):
                self.manager.connect(topology(), ports)
            self.assertGreater(listener.fileno(), -1)
        self.channel.start.assert_not_called()
        self.channel.terminate_group.assert_not_called()

    def test_partial_failure_rolls_back_only_new_connections(self):
        self.connect()
        state = self.manager.store.read()
        old_tx = state["nodes"]["tx"]["pid"]
        self.live.discard(state["nodes"]["rx"]["pid"])
        with (
            mock.patch.object(self.manager, "_require_free"),
            mock.patch.object(self.manager, "_ready", return_value=False),
        ):
            result = self.manager.connect(topology(), self.ports)
        self.assertFalse(result["ok"])
        self.assertEqual({old_tx}, self.live)
        self.assertEqual(["tx"], list(self.manager.store.read()["nodes"]))
        self.assertEqual(1, self.channel.terminate_group.call_count)

    def test_first_connect_failure_cleans_up_both_started_nodes(self):
        with (
            mock.patch.object(self.manager, "_require_free"),
            mock.patch.object(self.manager, "_ready", side_effect=[True, False]),
        ):
            result = self.manager.connect(topology(), self.ports)
        self.assertFalse(result["ok"])
        self.assertFalse(self.live)
        self.assertEqual({}, self.manager.store.read()["nodes"])

    def test_changed_configuration_requires_disconnect_without_side_effects(self):
        self.connect()
        self.ports["rx"] += 10
        with self.assertRaisesRegex(GarDomainError, "disconnect"):
            self.manager.connect(topology(), self.ports)
        self.assertEqual(2, self.channel.start.call_count)
        self.channel.terminate_group.assert_not_called()

    def test_scenario_cannot_reuse_a_connection_to_a_previous_host(self):
        self.connect()
        self.assertEqual(2, len(self.manager.urls(topology())))
        self.resolver.side_effect = lambda name: Workspace(
            name,
            name,
            "main",
            {"type": "local", "path": str(self.root)},
            selected_environments={"simulator": "ssh_remote"},
            ec2={"host": "different-sim"},
        )
        with self.assertRaisesRegex(GarDomainError, "設定が変わっています"):
            self.manager.urls(topology())
        self.assertEqual({}, self.manager.urls(topology(), overridden={"tx", "rx"}))
        self.channel.terminate_group.assert_not_called()

    def test_stale_or_reused_pid_is_not_signalled_and_status_does_not_write(self):
        self.connect()
        before = self.manager.store.path.read_bytes()
        self.live.clear()
        self.assertFalse(self.manager.status()["ok"])
        self.assertEqual(before, self.manager.store.path.read_bytes())
        self.assertTrue(self.manager.disconnect()["ok"])
        self.channel.terminate_group.assert_not_called()

    def test_stop_failure_keeps_receipts_for_retry(self):
        self.connect()
        with mock.patch.object(self.manager, "_stop", return_value=False):
            result = self.manager.disconnect()
        self.assertFalse(result["ok"])
        self.assertEqual(2, len(self.manager.store.read()["nodes"]))

    def test_missing_process_birth_time_never_authorizes_termination(self):
        self.connect()
        state = self.manager.store.read()
        for entry in state["nodes"].values():
            entry["start_time_ticks"] = None
        self.manager.store.write(state)
        self.assertFalse(self.manager.disconnect()["ok"])
        self.channel.terminate_group.assert_not_called()
        self.assertEqual(2, len(self.manager.store.read()["nodes"]))

    def test_different_system_files_do_not_share_ownership(self):
        self.connect()
        other = SystemConnections(self.root / "other.json", directory=self.root, channel=self.channel)
        self.assertTrue(other.disconnect()["ok"])
        self.assertEqual(2, len(self.live))
        self.channel.terminate_group.assert_not_called()

    def test_actual_local_listener_processes_are_owned_and_cleaned_up(self):
        channel = LocalProcessChannel()
        manager = SystemConnections(self.root / "local.json", directory=self.root, channel=channel)
        ports = []
        while len(ports) < 2:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
                if port not in ports:
                    ports.append(port)
        plan = {}
        for node, port in zip(("tx", "rx"), ports, strict=True):
            script = f"import socket,time; s=socket.socket(); s.bind(('127.0.0.1',{port})); s.listen(); time.sleep(60)"
            plan[node] = {
                "argv": [sys.executable, "-c", script],
                "port": port,
                "url": f"http://127.0.0.1:{port}",
                "workspace": node,
            }
        children = []
        popen = subprocess.Popen

        def retain_child(*args, **kwargs):
            child = popen(*args, **kwargs)
            children.append(child)
            return child

        with mock.patch("scripts.gar_lib.simulation.runtime.process.subprocess.Popen", side_effect=retain_child):
            try:
                with mock.patch.object(manager, "_plan", return_value=plan):
                    result = manager.connect(topology(), {})
                self.assertTrue(result["ok"], result)
                self.assertEqual(2, len(manager.urls()))
            finally:
                try:
                    self.assertTrue(manager.disconnect()["ok"])
                finally:
                    for child in children:
                        child.wait(timeout=5)

    def test_cli_connection_status_and_disconnect_emit_single_json_without_system_file(self):
        with mock.patch.dict("os.environ", {"GAR_PORT_FORWARD_STATE_DIR": str(self.root)}):
            for action in (("status", "connections"), ("disconnect",)):
                output, errors = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                    result = main(["system", *action, "--file", str(self.root / "missing.json"), "--json"])
                self.assertEqual(0, result)
                self.assertTrue(json.loads(output.getvalue())["ok"])
                self.assertEqual("", errors.getvalue())

    def test_system_stop_uses_reverse_order_and_preserves_connections(self):
        calls = []

        def gar(workspace):
            runtime = SimpleNamespace(stop=lambda **options: calls.append((workspace, options)) or 0)
            return SimpleNamespace(sim=SimpleNamespace(runtime=runtime))

        report = SystemOrchestrator(topology(), workspace_resolver=lambda name: name, gar_factory=gar).run("stop")
        self.assertTrue(report.ok)
        self.assertEqual([("Local/rx", {"keep_port_forward": True}), ("Local/tx", {"keep_port_forward": True})], calls)

    def test_json_boundary_sets_context_and_retains_captured_diagnostics(self):
        from scripts.gar_lib.commands.system import run_system_command

        def run(*_args):
            self.assertTrue(JSON_OUTPUT.get())
            print("progress")
            print("detail", file=sys.stderr)
            return 1, {"ok": False}

        output, errors = io.StringIO(), io.StringIO()
        with (
            mock.patch("scripts.gar_lib.commands.system._run_args", side_effect=run),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
        ):
            self.assertEqual(1, run_system_command(SimpleNamespace(system_action="connect", json_output=True)))
        self.assertEqual("progress", json.loads(output.getvalue())["output"])
        self.assertEqual("detail", json.loads(output.getvalue())["diagnostics"])
        self.assertFalse(JSON_OUTPUT.get())
        self.assertEqual("", errors.getvalue())

    def test_failed_node_diagnostic_retains_build_id_evidence(self):
        diagnostic = {
            "ok": False,
            "components": {"app": {"expected_build_id": "B", "running_build_id": "A", "build_id_match": False}},
        }
        gar = mock.Mock()
        gar.sim.diag.return_value = SimpleNamespace(exit_code=1, to_payload=lambda: diagnostic)
        gar.sim.artifacts.latest.side_effect = GarDomainError("no runtime snapshot")
        report = SystemOrchestrator(topology(), workspace_resolver=lambda name: name, gar_factory=lambda _: gar).run(
            "diag"
        )
        self.assertFalse(report.ok)
        self.assertEqual("A", report.nodes[0]["diagnostic"]["components"]["app"]["running_build_id"])
