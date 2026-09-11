from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.gar_lib.core.artifact import Artifact
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.system.model import topology_from_value
from scripts.gar_lib.system.orchestrator import SystemOrchestrator
from scripts.gar_lib.system.scenario import HttpBridgeScenarioAdapter, load_scenario, run_scenario, scenario_from_value


def topology():
    return topology_from_value(
        {
            "schema_version": 1,
            "name": "Example",
            "nodes": [
                {
                    "id": "tx",
                    "workspace": "Local/TX",
                    "app": "gar-stream-tx",
                    "role": "source",
                    "environment": "sim",
                    "runtime_env": {},
                },
                {
                    "id": "rx",
                    "workspace": "Local/RX",
                    "app": "gar-stream-rx",
                    "role": "receiver",
                    "environment": "sim",
                    "runtime_env": {},
                },
            ],
            "links": [],
            "order": ["tx", "rx"],
        }
    )


def scenario_value():
    return {
        "schema_version": 1,
        "name": "neutral-nine-stage",
        "steps": [
            {"type": "command", "node": "tx", "action": "rotate", "params": {"device": "rotary", "direction": 1}},
            {"type": "observe", "node": "tx", "metric": "tx.sources", "path": "source.count"},
            {"type": "assert", "metric": "tx.sources", "op": "gte", "value": 1},
            {"type": "command", "node": "rx", "action": "press", "params": {"device": "rotary"}},
            {"type": "observe", "node": "rx", "metric": "rx.frames", "path": "frames.received"},
            {"type": "assert", "metric": "rx.frames", "op": "gt", "value": 0},
            {"type": "command", "node": "tx", "via": "runtime", "action": "stop"},
            {"type": "wait", "milliseconds": 1},
            {"type": "command", "node": "tx", "via": "runtime", "action": "start"},
        ],
    }


class FakeScenarioAdapter:
    def __init__(self):
        self.commands: list[tuple[str, str, str, dict[str, object]]] = []

    def command(self, node: str, via: str, action: str, params: dict[str, object]) -> object:
        self.commands.append((node, via, action, dict(params)))
        return {"ok": True}

    def metrics(self, node: str, application: str) -> object:
        assert application == f"gar-stream-{node}"
        return {"source": {"count": 1}, "frames": {"received": 7}}


class ManualClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class GarSystemScenarioTest(unittest.TestCase):
    def test_product_neutral_dsl_represents_nine_stage_lifecycle_and_metrics(self) -> None:
        scenario = scenario_from_value(scenario_value(), topology())
        adapter = FakeScenarioAdapter()
        report = run_scenario(scenario, adapter=adapter, sleep=lambda _: None)

        self.assertTrue(report.ok)
        self.assertEqual(9, len(report.steps))
        self.assertEqual({"tx.sources": 1, "rx.frames": 7}, report.metrics)
        self.assertEqual(["bridge", "bridge", "runtime", "runtime"], [call[1] for call in adapter.commands])
        self.assertTrue(all(item["ok"] for item in report.assertions))

    def test_assertion_failure_is_machine_readable_and_stops_following_steps(self) -> None:
        value = scenario_value()
        value["steps"] = [
            {"type": "observe", "node": "tx", "metric": "tx.frames", "path": "frames.received"},
            {"type": "assert", "metric": "tx.frames", "op": "gt", "value": 99},
            {"type": "command", "node": "tx", "action": "press", "params": {"device": "rotary"}},
        ]
        report = run_scenario(
            scenario_from_value(value, topology()), adapter=FakeScenarioAdapter(), sleep=lambda _: None
        )

        self.assertFalse(report.ok)
        self.assertEqual(2, report.failures[0]["index"])
        self.assertEqual(2, len(report.steps))
        self.assertFalse(report.assertions[0]["ok"])

    def test_declared_cleanup_restarts_runtime_after_assertion_failure(self) -> None:
        value = {
            "schema_version": 1,
            "name": "recover-source",
            "steps": [
                {"type": "command", "node": "tx", "via": "runtime", "action": "stop", "params": {}},
                {"type": "observe", "node": "tx", "metric": "tx.frames", "path": "frames.received"},
                {"type": "assert", "metric": "tx.frames", "op": "gt", "value": 99},
            ],
            "cleanup": [{"type": "command", "node": "tx", "via": "runtime", "action": "start", "params": {}}],
        }
        adapter = FakeScenarioAdapter()
        report = run_scenario(scenario_from_value(value, topology()), adapter=adapter, sleep=lambda _: None)

        self.assertFalse(report.ok)
        self.assertEqual(
            [("tx", "runtime", "stop"), ("tx", "runtime", "start")], [call[:3] for call in adapter.commands]
        )
        self.assertTrue(report.cleanup[0]["ok"])

    def test_explicit_runtime_restart_makes_a_counter_scenario_repeatable(self) -> None:
        value = {
            "schema_version": 1,
            "name": "repeatable-counter",
            "steps": [
                {"type": "command", "node": "tx", "via": "runtime", "action": "stop", "params": {}},
                {"type": "command", "node": "tx", "via": "runtime", "action": "start", "params": {}},
                {"type": "observe", "node": "tx", "metric": "tx.counter", "path": "frames.count"},
                {"type": "assert", "metric": "tx.counter", "op": "eq", "value": 1},
            ],
            "cleanup": [{"type": "command", "node": "tx", "via": "runtime", "action": "start", "params": {}}],
        }

        class RestartingCounterAdapter(FakeScenarioAdapter):
            def __init__(self) -> None:
                super().__init__()
                self.running = True
                self.counter = 0

            def command(self, node: str, via: str, action: str, params: dict[str, object]) -> object:
                result = super().command(node, via, action, params)
                if via == "runtime" and action == "stop":
                    self.running = False
                elif via == "runtime" and action == "start":
                    self.running = True
                    self.counter = 0
                return result

            def metrics(self, node: str, application: str) -> object:
                if self.running:
                    self.counter += 1
                return {"frames": {"count": self.counter}}

        scenario = scenario_from_value(value, topology())
        adapter = RestartingCounterAdapter()
        first = run_scenario(scenario, adapter=adapter, sleep=lambda _: None)
        second = run_scenario(scenario, adapter=adapter, sleep=lambda _: None)

        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertEqual(1, first.metrics["tx.counter"])
        self.assertEqual(1, second.metrics["tx.counter"])

    def test_canonical_schema_rejects_compatibility_aliases(self) -> None:
        for invalid in (
            {"kind": "wait", "milliseconds": 1},
            {"type": "wait", "seconds": 1},
            {"type": "command", "node": "tx", "action": "service.stop", "params": {}},
        ):
            value = {"schema_version": 1, "name": "strict", "steps": [invalid]}
            with self.subTest(invalid=invalid), self.assertRaises(GarDomainError):
                scenario_from_value(value, topology())

    def test_http_adapter_uses_rotary_and_metrics_endpoints(self) -> None:
        adapter = HttpBridgeScenarioAdapter({"rx": "http://127.0.0.1:8080"})
        with mock.patch.object(adapter, "_request", return_value={"ok": True}) as request:
            adapter.command("rx", "bridge", "rotate", {"device": "rotary", "direction": 1})
            adapter.command("rx", "bridge", "press", {"device": "rotary"})
            adapter.metrics("rx", "gar-stream-rx")

        self.assertEqual(
            [
                mock.call("rx", "POST", "/api/rotary/rotate", {"direction": 1}),
                mock.call("rx", "POST", "/api/rotary/press", {}),
                mock.call("rx", "GET", "/api/metrics/gar-stream-rx", None),
            ],
            request.call_args_list,
        )

    def test_eventual_observe_and_assertion_poll_without_busy_loop(self) -> None:
        value = {
            "schema_version": 1,
            "name": "eventual",
            "steps": [
                {
                    "type": "observe",
                    "node": "tx",
                    "metric": "tx.frames",
                    "path": "frames.received",
                    "timeout_ms": 10,
                    "interval_ms": 1,
                },
                {
                    "type": "assert",
                    "metric": "tx.frames",
                    "op": "gte",
                    "value": 2,
                    "timeout_ms": 10,
                    "interval_ms": 1,
                },
            ],
        }

        class EventualAdapter(FakeScenarioAdapter):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def metrics(self, node: str, application: str) -> object:
                self.calls += 1
                if self.calls == 1:
                    return {"frames": {}}
                return {"frames": {"received": 2}}

        report = run_scenario(scenario_from_value(value, topology()), adapter=EventualAdapter())

        self.assertTrue(report.ok)
        self.assertGreaterEqual(report.steps[0]["attempts"], 2)
        self.assertGreaterEqual(report.assertions[0]["attempts"], 1)

    def test_eventual_assertion_retries_none_until_metric_is_numeric(self) -> None:
        value = {
            "schema_version": 1,
            "name": "latency-settles",
            "steps": [
                {"type": "observe", "node": "rx", "metric": "rx.latency", "path": "frames.latency"},
                {
                    "type": "assert",
                    "metric": "rx.latency",
                    "op": "gte",
                    "value": 0,
                    "timeout_ms": 30,
                    "interval_ms": 10,
                },
            ],
        }

        class SettlingAdapter(FakeScenarioAdapter):
            def __init__(self) -> None:
                super().__init__()
                self.metric_calls = 0

            def metrics(self, node: str, application: str) -> object:
                self.metric_calls += 1
                return {"frames": {"latency": None if self.metric_calls == 1 else 2.5}}

        clock = ManualClock()
        report = run_scenario(
            scenario_from_value(value, topology()),
            adapter=SettlingAdapter(),
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        self.assertTrue(report.ok)
        self.assertEqual(2.5, report.metrics["rx.latency"])
        self.assertEqual(2, report.assertions[0]["attempts"])
        self.assertEqual([0.01], clock.sleeps)

    def test_permanent_none_is_structured_after_polling_and_cleanup_still_runs(self) -> None:
        value = {
            "schema_version": 1,
            "name": "latency-never-settles",
            "steps": [
                {"type": "command", "node": "tx", "via": "runtime", "action": "stop", "params": {}},
                {"type": "observe", "node": "rx", "metric": "rx.latency", "path": "frames.latency"},
                {
                    "type": "assert",
                    "metric": "rx.latency",
                    "op": "gte",
                    "value": 0,
                    "timeout_ms": 30,
                    "interval_ms": 10,
                },
            ],
            "cleanup": [{"type": "command", "node": "tx", "via": "runtime", "action": "start", "params": {}}],
        }

        class NoneAdapter(FakeScenarioAdapter):
            def metrics(self, node: str, application: str) -> object:
                return {"frames": {"latency": None}}

        adapter = NoneAdapter()
        clock = ManualClock()
        report = run_scenario(
            scenario_from_value(value, topology()),
            adapter=adapter,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        self.assertFalse(report.ok)
        self.assertGreater(report.assertions[0]["attempts"], 1)
        self.assertFalse(report.assertions[0]["ok"])
        self.assertIn("numeric assertion", report.assertions[0]["error"])
        self.assertEqual(3, report.failures[0]["index"])
        self.assertIn("numeric assertion", report.failures[0]["error"])
        self.assertTrue(report.cleanup[0]["ok"])
        self.assertEqual(("tx", "runtime", "start"), adapter.commands[-1][:3])

    def test_comparison_error_without_timeout_fails_immediately(self) -> None:
        value = {
            "schema_version": 1,
            "name": "no-retry",
            "steps": [
                {"type": "observe", "node": "rx", "metric": "rx.latency", "path": "frames.latency"},
                {"type": "assert", "metric": "rx.latency", "op": "gte", "value": 0},
            ],
        }

        class NoneAdapter(FakeScenarioAdapter):
            def metrics(self, node: str, application: str) -> object:
                return {"frames": {"latency": None}}

        clock = ManualClock()
        report = run_scenario(
            scenario_from_value(value, topology()),
            adapter=NoneAdapter(),
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        self.assertFalse(report.ok)
        self.assertEqual(1, report.assertions[0]["attempts"])
        self.assertEqual([], clock.sleeps)

    def test_assertion_can_compare_two_previously_observed_metrics(self) -> None:
        value = {
            "schema_version": 1,
            "name": "metric-delta",
            "steps": [
                {"type": "observe", "node": "tx", "metric": "tx.before", "path": "frames.before"},
                {"type": "observe", "node": "tx", "metric": "tx.after", "path": "frames.after"},
                {"type": "assert", "metric": "tx.after", "op": "gt", "value_metric": "tx.before"},
            ],
        }

        class MetricsAdapter(FakeScenarioAdapter):
            def metrics(self, node: str, application: str) -> object:
                return {"frames": {"before": 5, "after": 6}}

        report = run_scenario(scenario_from_value(value, topology()), adapter=MetricsAdapter())

        self.assertTrue(report.ok)
        self.assertEqual(5, report.assertions[0]["expected"])
        self.assertEqual("tx.before", report.assertions[0]["expected_metric"])

    def test_value_metric_is_strict_and_requires_a_prior_observation(self) -> None:
        for assertion in (
            {"type": "assert", "metric": "tx.value", "op": "gt", "value": 1, "value_metric": "tx.before"},
            {"type": "assert", "metric": "tx.value", "op": "gt", "value_metric": "tx.before"},
        ):
            value = {
                "schema_version": 1,
                "name": "invalid-metric-compare",
                "steps": [
                    {"type": "observe", "node": "tx", "metric": "tx.value", "path": "frames.received"},
                    assertion,
                ],
            }
            with self.subTest(assertion=assertion), self.assertRaises(GarDomainError):
                scenario_from_value(value, topology())

    def test_bridge_override_requires_a_plain_http_origin(self) -> None:
        for value in (
            "https://example.test:8443",
            "http://127.0.0.1:8080/",
        ):
            self.assertEqual(value.rstrip("/"), SystemOrchestrator._bridge_url(value, "tx"))
        for value in (
            "http://user@example.test",
            "http://example.test/path",
            "http://example.test?query=yes",
            "http://example.test#fragment",
            "http://example.test:99999",
        ):
            with self.subTest(value=value), self.assertRaises(GarDomainError):
                SystemOrchestrator._bridge_url(value, "tx")

    def test_scenario_rejects_non_finite_json_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text('{"schema_version":1,"name":"bad","steps":[],"value":NaN}', encoding="utf-8")
            with self.assertRaises(GarDomainError):
                load_scenario(path, topology())

    def test_http_metrics_rejects_non_finite_json_numbers(self) -> None:
        class Response:
            def __enter__(self) -> Response:
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self, _size: int) -> bytes:
                return b'{"frames":NaN}'

        adapter = HttpBridgeScenarioAdapter({"tx": "http://127.0.0.1:8080"})
        with mock.patch("scripts.gar_lib.system.scenario.urllib.request.urlopen", return_value=Response()):
            with self.assertRaises(GarDomainError):
                adapter.metrics("tx", "gar-stream-tx")

    def test_rejects_physical_target_and_unknown_bridge_action_before_execution(self) -> None:
        value = scenario_value()
        value["steps"][0]["action"] = "unknown"  # type: ignore[index]
        with self.assertRaisesRegex(Exception, "bridge command"):
            scenario_from_value(value, topology())

        target_topology = topology_from_value(
            {
                "schema_version": 1,
                "name": "target",
                "nodes": [
                    {
                        "id": "tx",
                        "workspace": "Local/TX",
                        "app": "tx",
                        "role": "source",
                        "environment": "target",
                        "runtime_env": {},
                    },
                    {
                        "id": "rx",
                        "workspace": "Local/RX",
                        "app": "rx",
                        "role": "receiver",
                        "environment": "sim",
                        "runtime_env": {},
                    },
                ],
                "links": [],
                "order": ["tx", "rx"],
            }
        )
        with self.assertRaisesRegex(Exception, "sim node"):
            scenario_from_value(scenario_value(), target_topology)

    def test_system_test_reports_node_health_and_artifact_build_ids(self) -> None:
        workspaces = {
            node: Workspace(
                id=node,
                name=f"Local/{node}",
                branch="main",
                connection={"type": "local", "path": "/tmp/product"},
                docker={"bridge_port": 8080},
            )
            for node in ("tx", "rx")
        }
        gar_instances = []
        for node in ("tx", "rx"):
            gar = mock.MagicMock()
            gar.sim.diag.return_value = SimpleNamespace(exit_code=0, to_payload=lambda: {"ok": True})
            gar.sim.artifacts.latest.side_effect = lambda kind, workspace, node=node: Artifact(
                kind=kind, workspace=workspace, bundle_path=Path(f"/tmp/{node}/{kind.value}")
            )
            gar_instances.append(gar)
        metadata = SimpleNamespace(build_id="build-123", checksums={"run": "a" * 64})
        scenario = scenario_from_value(
            {
                "schema_version": 1,
                "name": "observe",
                "steps": [{"type": "observe", "node": "tx", "metric": "tx.frames", "path": "frames.received"}],
            },
            topology(),
        )
        with mock.patch("scripts.gar_lib.system.orchestrator.load_artifact_metadata", return_value=metadata):
            report = SystemOrchestrator(
                topology(),
                workspace_resolver=lambda name: workspaces[name.rsplit("/", 1)[-1].lower()],
                gar_factory=mock.Mock(side_effect=gar_instances),
            ).run("test", scenario=scenario, scenario_adapter=FakeScenarioAdapter())

        self.assertTrue(report.ok)
        payload = report.as_dict()
        self.assertTrue(payload["nodes"][0]["health"])
        self.assertEqual("build-123", payload["nodes"][0]["artifacts"][0]["build_id"])
        self.assertEqual({"run": "a" * 64}, payload["nodes"][0]["artifacts"][0]["checksums"])
        self.assertTrue(payload["scenario"]["ok"])


if __name__ == "__main__":
    unittest.main()
