from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.gar_lib.cli import main
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.system.model import topology_from_value
from scripts.gar_lib.system.orchestrator import SystemOrchestrator


def topology() -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": "Example",
        "nodes": [
            {
                "id": "tx",
                "workspace": "Local/TX",
                "app": "stream-tx",
                "role": "source",
                "environment": "sim",
                "runtime_env": {"PEER_IP": {"node_private_ip": "rx"}, "MEDIA_PORT": {"link_port": "media"}},
            },
            {
                "id": "rx",
                "workspace": "Local/RX",
                "app": "stream-rx",
                "role": "receiver",
                "environment": "target",
                "runtime_env": {"TX_IP": {"node_private_ip": "tx"}},
            },
        ],
        "links": [{"id": "media", "from": "tx", "to": "rx", "protocol": "rtp/udp", "port": 5600}],
        "order": ["tx", "rx"],
    }


def workspace(name: str, private_ip: str) -> Workspace:
    return Workspace(
        id=name,
        name=name,
        branch="main",
        connection={"type": "local", "path": "/tmp/product"},
        ec2={"private_ip": private_ip},
    )


class GarSystemModelTest(unittest.TestCase):
    def test_schema_requires_all_nodes_once_in_order(self) -> None:
        value = topology()
        value["order"] = ["tx"]
        with self.assertRaisesRegex(GarDomainError, "ちょうど1回"):
            topology_from_value(value)

    def test_schema_rejects_unknown_fields_unsafe_environment_and_bad_port(self) -> None:
        value = topology()
        value["unexpected"] = True
        with self.assertRaisesRegex(GarDomainError, "未対応"):
            topology_from_value(value)
        value = topology()
        value["nodes"][0]["runtime_env"] = {"bad-name": {"literal": "x"}}  # type: ignore[index]
        with self.assertRaisesRegex(GarDomainError, "安全"):
            topology_from_value(value)
        value = topology()
        value["links"][0]["port"] = 0  # type: ignore[index]
        with self.assertRaisesRegex(GarDomainError, "65535"):
            topology_from_value(value)
        value = topology()
        value["links"][0]["protocol"] = "rtp/sctp"  # type: ignore[index]
        with self.assertRaisesRegex(GarDomainError, "tcp または udp"):
            topology_from_value(value)

    def test_schema_requires_explicit_runtime_env_for_every_node(self) -> None:
        value = topology()
        del value["nodes"][0]["runtime_env"]  # type: ignore[index]

        with self.assertRaisesRegex(GarDomainError, "runtime_env"):
            topology_from_value(value)

    def test_schema_rejects_unsafe_application_before_orchestration(self) -> None:
        value = topology()
        value["nodes"][0]["app"] = "../../unsafe"  # type: ignore[index]

        with self.assertRaisesRegex(GarDomainError, "application"):
            topology_from_value(value)


class GarSystemOrchestratorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workspaces = {
            "Local/TX": workspace("Local/TX", "10.0.0.10"),
            "Local/RX": workspace("Local/RX", "10.0.0.11"),
        }

    def _orchestrator(self, gar_factory: mock.Mock) -> SystemOrchestrator:
        return SystemOrchestrator(
            topology_from_value(topology()),
            workspace_resolver=lambda selector: self.workspaces[selector],
            gar_factory=gar_factory,
        )

    def test_build_is_ordered_and_never_resolves_private_ip(self) -> None:
        calls: list[str] = []
        tx, rx = mock.MagicMock(), mock.MagicMock()
        tx.sim.build.side_effect = lambda: calls.append("tx.sim.build")
        rx.target.build.side_effect = lambda: calls.append("rx.target.build")
        factory = mock.Mock(side_effect=[tx, rx])
        self.workspaces["Local/TX"] = workspace("Local/TX", "")
        self.workspaces["Local/RX"] = workspace("Local/RX", "")
        report = self._orchestrator(factory).run("build")
        self.assertTrue(report.ok)
        self.assertEqual(["tx.sim.build", "rx.target.build"], calls)
        tx.sim.runtime.configure_system_env.assert_not_called()

    def test_deploy_injects_resolved_env_in_declared_order(self) -> None:
        calls: list[str] = []
        tx, rx = mock.MagicMock(), mock.MagicMock()
        tx.sim.deploy.side_effect = lambda: calls.append("sim.deploy")
        tx.sim.runtime.configure_system_env.side_effect = lambda app, values: calls.append(
            f"env:{app}:{values['PEER_IP']}"
        )

        def deploy_target(**kwargs: object) -> SimpleNamespace:
            values = kwargs["system_env"]
            assert isinstance(values, dict)
            calls.append(f"target.deploy:{kwargs['system_env_app']}:{values['TX_IP']}")
            return SimpleNamespace(configuration=SimpleNamespace(destination="/etc/gar/system/stream-rx.env"))

        rx.target.deploy_report.side_effect = deploy_target
        report = self._orchestrator(mock.Mock(side_effect=[tx, rx])).run("deploy")
        self.assertTrue(report.ok)
        self.assertEqual(
            [
                "sim.deploy",
                "env:stream-tx:10.0.0.11",
                "target.deploy:stream-rx:10.0.0.10",
            ],
            calls,
        )
        self.assertEqual("5600", tx.sim.runtime.configure_system_env.call_args.args[1]["MEDIA_PORT"])

    def test_deploy_rejects_missing_runtime_binding_before_changing_that_node(self) -> None:
        tx, rx = mock.MagicMock(), mock.MagicMock()
        self.workspaces["Local/RX"] = workspace("Local/RX", "")

        report = self._orchestrator(mock.Mock(side_effect=[tx, rx])).run("deploy")

        self.assertFalse(report.ok)
        tx.sim.deploy.assert_not_called()
        tx.sim.runtime.configure_system_env.assert_not_called()

    def test_start_uses_no_port_forward_and_converges_target_after_runtime_env(self) -> None:
        tx, rx = mock.MagicMock(), mock.MagicMock()
        tx.sim.runtime.start.return_value = 0
        report = self._orchestrator(mock.Mock(side_effect=[tx, rx])).run("start")
        self.assertTrue(report.ok)
        tx.sim.runtime.start.assert_called_once_with(no_port_forward=True)
        rx.target.deploy.assert_not_called()
        rx.target.configure_system_env.assert_not_called()
        rx.target.start.assert_called_once_with(app="stream-rx", system_env={"TX_IP": "10.0.0.10"})

    def test_test_reports_diagnostics_without_resolving_runtime_env_or_private_ips(self) -> None:
        tx, rx = mock.MagicMock(), mock.MagicMock()
        tx.sim.diag.return_value.exit_code = 0
        tx.sim.diag.return_value.as_dict.return_value = {"ok": True}
        rx.target.diag.return_value.exit_code = 0
        rx.target.diag.return_value.as_dict.return_value = {"ok": True}
        self.workspaces["Local/TX"] = workspace("Local/TX", "")
        self.workspaces["Local/RX"] = workspace("Local/RX", "")
        report = self._orchestrator(mock.Mock(side_effect=[tx, rx])).run("test")
        self.assertTrue(report.ok)
        self.assertNotIn("from_private_ip", report.links[0])
        self.assertNotIn("topology_env", report.nodes[0])

    def test_links_generate_firewall_and_diagnostic_plans(self) -> None:
        tx, rx = mock.MagicMock(), mock.MagicMock()
        tx.sim.status.return_value.exit_code = 0
        rx.target.status.return_value.exit_code = 0

        report = self._orchestrator(mock.Mock(side_effect=[tx, rx])).run("status")

        self.assertTrue(report.ok)
        link = report.links[0]
        self.assertEqual(
            [
                {"node": "tx", "direction": "egress", "peer": "rx", "protocol": "udp", "port": 5600},
                {"node": "rx", "direction": "ingress", "peer": "tx", "protocol": "udp", "port": 5600},
            ],
            link["firewall"],
        )
        self.assertEqual({"from": "tx", "to": "rx", "protocol": "udp", "port": 5600}, link["diagnostic_target"])


class GarSystemCliTest(unittest.TestCase):
    def test_json_failure_is_one_stdout_object_and_empty_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text("{}", encoding="utf-8")
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(["system", "build", "--file", str(path), "--json"])
        self.assertEqual(1, code)
        self.assertEqual("", stderr.getvalue())
        self.assertFalse(json.loads(stdout.getvalue())["ok"])

    def test_system_test_passes_scenario_and_safe_bridge_overrides_as_single_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            topology_path = root / "system.json"
            scenario_path = root / "scenario.json"
            value = topology()
            value["nodes"][1]["environment"] = "sim"  # type: ignore[index]
            topology_path.write_text(json.dumps(value), encoding="utf-8")
            scenario_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "observe",
                        "steps": [{"type": "observe", "node": "tx", "metric": "tx.frames", "path": "frames.sent"}],
                    }
                ),
                encoding="utf-8",
            )
            expected = {"schema_version": 1, "ok": True, "name": "Example"}
            orchestrator = mock.Mock()
            orchestrator.return_value.run.return_value = SimpleNamespace(exit_code=0, as_dict=lambda: expected)
            stdout, stderr = io.StringIO(), io.StringIO()
            with (
                mock.patch("scripts.gar_lib.commands.system.SystemOrchestrator", orchestrator),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                code = main(
                    [
                        "system",
                        "test",
                        "--file",
                        str(topology_path),
                        "--scenario",
                        str(scenario_path),
                        "--bridge",
                        "tx=http://127.0.0.1:8080",
                        "--json",
                    ]
                )
        self.assertEqual(0, code)
        self.assertEqual("", stderr.getvalue())
        self.assertEqual(expected, json.loads(stdout.getvalue()))
        self.assertEqual(
            {"tx": "http://127.0.0.1:8080"}, orchestrator.return_value.run.call_args.kwargs["bridge_overrides"]
        )


if __name__ == "__main__":
    unittest.main()
