"""Ordered orchestration of a :mod:`gar system` topology."""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from scripts.gar_lib.api import Gar
from scripts.gar_lib.artifacts.metadata import load_artifact_metadata
from scripts.gar_lib.commands.workspace_resolver import resolve_workspace
from scripts.gar_lib.core.artifact import ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.system.model import SystemLink, SystemNode, SystemTopology
from scripts.gar_lib.system.scenario import (
    BridgeScenarioAdapter,
    HttpBridgeScenarioAdapter,
    ScenarioReport,
    SystemScenario,
    run_scenario,
)


class _SystemScenarioAdapter:
    """Keep bridge I/O and GAR lifecycle actions on their existing boundaries."""

    def __init__(
        self,
        bridge_urls: Mapping[str, str],
        workspaces: Mapping[str, Workspace],
        gar_factory: Callable[[Workspace], Gar],
    ):
        self.bridge = HttpBridgeScenarioAdapter(bridge_urls)
        self.workspaces = workspaces
        self.gar_factory = gar_factory

    def command(self, node: str, via: str, action: str, params: Mapping[str, object]) -> object:
        if via == "bridge":
            return self.bridge.command(node, via, action, params)
        if via != "runtime":
            raise GarDomainError(f"unknown scenario command transport: {via}")
        workspace = self.workspaces.get(node)
        if workspace is None:
            raise GarDomainError(f"scenario nodeのworkspaceを解決できません: {node}")
        runtime = self.gar_factory(workspace).sim.runtime
        if action == "start":
            exit_code = runtime.start(no_port_forward=True)
        elif action == "stop":
            exit_code = runtime.stop(keep_port_forward=True)
        else:
            raise GarDomainError(f"unknown scenario runtime action: {action}")
        if exit_code:
            raise GarDomainError(f"scenario runtime {action} failed (exit {exit_code})")
        return {"action": action, "exit_code": exit_code}

    def metrics(self, node: str, application: str) -> object:
        return self.bridge.metrics(node, application)


@dataclass(frozen=True)
class SystemReport:
    command: str
    name: str
    nodes: list[dict[str, object]]
    links: list[dict[str, object]]
    failures: list[dict[str, str]]
    scenario: ScenarioReport | None = None

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": 1,
            "command": f"system.{self.command}",
            "name": self.name,
            "ok": self.ok,
            "exit_code": self.exit_code,
            "nodes": self.nodes,
            "links": self.links,
            "failures": self.failures,
        }
        if self.scenario is not None:
            payload["scenario"] = self.scenario.as_dict()
        return payload


class SystemOrchestrator:
    """Call GAR's public node APIs in the topology's declared order."""

    def __init__(
        self,
        topology: SystemTopology,
        *,
        workspace_resolver: Callable[[str], Workspace] = resolve_workspace,
        gar_factory: Callable[[Workspace], Gar] = Gar,
    ):
        self.topology = topology
        self.workspace_resolver = workspace_resolver
        self.gar_factory = gar_factory

    def run(
        self,
        command: str,
        *,
        scenario: SystemScenario | None = None,
        bridge_overrides: Mapping[str, str] | None = None,
        scenario_adapter: BridgeScenarioAdapter | None = None,
    ) -> SystemReport:
        if command not in {"build", "deploy", "start", "stop", "status", "diag", "test"}:
            raise GarDomainError(f"未対応の system action: {command}")
        workspaces, failures = self._resolve_workspaces()
        nodes: list[dict[str, object]] = []
        node_order = reversed(self.topology.order) if command == "stop" else self.topology.order
        for node_id in node_order:
            node = self.topology.nodes[node_id]
            workspace = workspaces.get(node_id)
            if workspace is None:
                nodes.append({"id": node.id, "workspace": node.workspace, "environment": node.environment, "ok": False})
                continue
            result = self._run_node(command, node, workspace, workspaces)
            nodes.append(result)
            if not result["ok"]:
                failures.append({"node": node.id, "action": command, "error": str(result["error"])})
        links = self._resolved_links(workspaces, failures, resolve_private_ips=command in {"deploy", "start"})
        scenario_report: ScenarioReport | None = None
        if scenario is not None:
            if command != "test":
                raise GarDomainError("scenario は system test でのみ実行できます")
            if failures:
                scenario_report = ScenarioReport(
                    scenario.name,
                    [],
                    {},
                    [],
                    [],
                    [{"error": "system diagnostics failed before scenario"}],
                )
            else:
                adapter = scenario_adapter or _SystemScenarioAdapter(
                    self._scenario_bridge_urls(scenario, workspaces, bridge_overrides or {}),
                    workspaces,
                    self.gar_factory,
                )
                scenario_report = run_scenario(scenario, adapter=adapter)
            if not scenario_report.ok:
                failures.append({"node": "system", "action": "scenario", "error": "scenario assertions failed"})
        return SystemReport(
            command=command,
            name=self.topology.name,
            nodes=nodes,
            links=links,
            failures=failures,
            scenario=scenario_report,
        )

    def _scenario_bridge_urls(
        self,
        scenario: SystemScenario,
        workspaces: Mapping[str, Workspace],
        overrides: Mapping[str, str],
    ) -> dict[str, str]:
        node_ids = {
            str(step["node"])
            for step in (*scenario.steps, *scenario.cleanup)
            if step["type"] == "observe" or (step["type"] == "command" and step["via"] == "bridge")
        }
        urls: dict[str, str] = {}
        for node_id in node_ids:
            override = overrides.get(node_id)
            if override is not None:
                urls[node_id] = self._bridge_url(override, node_id)
                continue
            workspace = workspaces.get(node_id)
            if workspace is None:
                raise GarDomainError(f"scenario nodeのworkspaceを解決できません: {node_id}")
            port = workspace.simulation_bridge_port
            if port is None:
                raise GarDomainError(
                    f"scenario bridge URLが未設定です: {node_id}。--bridge {node_id}=http://127.0.0.1:PORT を指定してください"
                )
            urls[node_id] = f"http://127.0.0.1:{port}"
        unknown = set(overrides) - set(self.topology.nodes)
        if unknown:
            raise GarDomainError(f"--bridge は存在しないnodeを参照しています: {', '.join(sorted(unknown))}")
        return urls

    @staticmethod
    def _bridge_url(value: str, node_id: str) -> str:
        parsed = urllib.parse.urlparse(value)
        try:
            valid_port = parsed.port is None or 1 <= parsed.port <= 65535
        except ValueError:
            valid_port = False
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or not valid_port
        ):
            raise GarDomainError(f"--bridge {node_id} はhttp(s) origin URLである必要があります")
        return value.rstrip("/")

    def _resolve_workspaces(self) -> tuple[dict[str, Workspace], list[dict[str, str]]]:
        resolved: dict[str, Workspace] = {}
        failures: list[dict[str, str]] = []
        for node_id in self.topology.order:
            node = self.topology.nodes[node_id]
            try:
                resolved[node_id] = self.workspace_resolver(node.workspace)
            except Exception as error:
                failures.append({"node": node.id, "action": "resolve", "error": str(error)})
        return resolved, failures

    def _run_node(
        self,
        command: str,
        node: SystemNode,
        workspace: Workspace,
        workspaces: dict[str, Workspace],
    ) -> dict[str, object]:
        result: dict[str, object] = {
            "id": node.id,
            "workspace": node.workspace,
            "app": node.app,
            "role": node.role,
            "environment": node.environment,
            "ok": True,
        }
        try:
            gar = self.gar_factory(workspace)
            if command == "build":
                if node.environment == "sim":
                    gar.sim.build()
                else:
                    gar.target.build()
            elif command == "deploy":
                result["deployment"] = self._deploy(gar, node, workspaces)
            elif command == "start":
                self._start(gar, node, workspaces)
            elif command == "stop":
                code = (
                    gar.sim.runtime.stop(keep_port_forward=True)
                    if node.environment == "sim"
                    else gar.target.stop(app=node.app).exit_code
                )
                if code:
                    raise GarDomainError(f"stop failed (exit {code})")
            elif command == "status":
                observation = self._status(gar, node)
                status = observation.exit_code
                result["status"] = status
                result["observation"] = self._report_payload(observation)
                if status:
                    raise GarDomainError(f"status failed (exit {status})")
            else:  # diag and test collect health plus artifact provenance.
                result["diagnostic"] = self._diag(gar, node)
                result["health"] = bool(result["diagnostic"].get("ok"))
                result["artifacts"] = self._artifact_observation(gar, node, workspace)
                if not result["health"]:
                    raise GarDomainError("diagnostic failed")
            return result
        except Exception as error:
            result["ok"] = False
            result["error"] = str(error)
            if details := getattr(error, "details", None):
                result["details"] = details
            return result

    def _deploy(self, gar: Gar, node: SystemNode, workspaces: dict[str, Workspace]) -> dict[str, object]:
        # Resolve every machine-local binding before changing the node.  A
        # missing peer must not leave a newly deployed artifact with stale
        # runtime configuration.
        values = self._runtime_env(node, workspaces)
        if node.environment == "sim":
            gar.sim.deploy()
            destination = gar.sim.runtime.configure_system_env(node.app, values)
            return {"system_env": destination}
        else:
            # Target validates compatibility before placing the env, then
            # deploys and converges the app against that same atomic file.
            deployed = gar.target.deploy_report(system_env_app=node.app, system_env=values)
            assert deployed.configuration is not None
            return {"system_env": deployed.configuration.destination}

    def _start(self, gar: Gar, node: SystemNode, workspaces: dict[str, Workspace]) -> None:
        values = self._runtime_env(node, workspaces)
        if node.environment == "sim":
            # Resolve network bindings at start too, so a changed private address is not stale.
            gar.sim.runtime.configure_system_env(node.app, values)
            exit_code = gar.sim.runtime.start(no_port_forward=True)
            if exit_code:
                raise GarDomainError(f"simulation runtime start failed (exit {exit_code})")
        else:
            # Re-resolve topology-owned bindings immediately before target
            # lifecycle convergence, so an address cannot become stale.
            gar.target.start(app=node.app, system_env=values)

    def _status(self, gar: Gar, node: SystemNode):
        if node.environment == "sim":
            return gar.sim.status()
        return gar.target.status(app=node.app)

    def _diag(self, gar: Gar, node: SystemNode) -> dict[str, object]:
        report = gar.sim.diag() if node.environment == "sim" else gar.target.diag(app=node.app)
        return self._report_payload(report)

    @staticmethod
    def _report_payload(report) -> dict[str, object]:
        if callable(getattr(report, "as_dict", None)):
            payload = report.as_dict()
        elif callable(getattr(report, "to_payload", None)):
            payload = report.to_payload()
        else:
            payload = {"exit_code": report.exit_code}
        if report.exit_code:
            payload["ok"] = False
        return payload

    @staticmethod
    def _artifact_observation(gar: Gar, node: SystemNode, workspace: Workspace) -> list[dict[str, object]]:
        kinds = (
            (ArtifactKind.SIM_APP, ArtifactKind.SIM_RUNTIME)
            if node.environment == "sim"
            else (ArtifactKind.TARGET_APP,)
        )
        store = gar.sim.artifacts if node.environment == "sim" else gar.target.artifacts
        observations: list[dict[str, object]] = []
        for kind in kinds:
            try:
                artifact = store.latest(kind, workspace)
                metadata = load_artifact_metadata(Path(artifact.bundle_path))
                observations.append(
                    {
                        "kind": kind.value,
                        "available": True,
                        "build_id": metadata.build_id if metadata is not None else None,
                        "checksums": dict(metadata.checksums) if metadata is not None else {},
                    }
                )
            except Exception as error:
                observations.append({"kind": kind.value, "available": False, "error": str(error)})
        return observations

    def _runtime_env(self, node: SystemNode, workspaces: dict[str, Workspace]) -> dict[str, str]:
        values: dict[str, str] = {}
        for name, source in node.runtime_env.items():
            if source.kind == "literal":
                values[name] = str(source.value)
            elif source.kind == "link_port":
                values[name] = str(self.topology.links[str(source.value)].port)
            else:
                peer = workspaces[str(source.value)]
                private_ip = peer.simulation_private_ip
                if not private_ip:
                    raise GarDomainError(f"node {source.value} のprivate_ipが未設定です")
                values[name] = private_ip
        return values

    def _resolved_links(
        self,
        workspaces: dict[str, Workspace],
        failures: list[dict[str, str]],
        *,
        resolve_private_ips: bool,
    ) -> list[dict[str, object]]:
        endpoints: list[dict[str, object]] = []
        for link in self.topology.links.values():
            entry: dict[str, object] = {
                "id": link.id,
                "from": link.from_node,
                "to": link.to_node,
                "protocol": link.protocol,
                "port": link.port,
                "firewall": self._firewall_plan(link),
                "diagnostic_target": self._diagnostic_target(link),
            }
            if not resolve_private_ips:
                entry["ok"] = True
                endpoints.append(entry)
                continue
            try:
                entry["from_private_ip"] = self._private_ip(link, "from", workspaces)
                entry["to_private_ip"] = self._private_ip(link, "to", workspaces)
                entry["ok"] = True
            except GarDomainError as error:
                entry["ok"] = False
                entry["error"] = str(error)
                failures.append({"node": "system", "action": "resolve-links", "error": str(error)})
            endpoints.append(entry)
        return endpoints

    @staticmethod
    def _transport_protocol(link: SystemLink) -> str:
        return link.protocol.rsplit("/", 1)[-1].lower()

    @classmethod
    def _firewall_plan(cls, link: SystemLink) -> list[dict[str, object]]:
        transport = cls._transport_protocol(link)
        return [
            {
                "node": link.from_node,
                "direction": "egress",
                "peer": link.to_node,
                "protocol": transport,
                "port": link.port,
            },
            {
                "node": link.to_node,
                "direction": "ingress",
                "peer": link.from_node,
                "protocol": transport,
                "port": link.port,
            },
        ]

    @classmethod
    def _diagnostic_target(cls, link: SystemLink) -> dict[str, object]:
        return {
            "from": link.from_node,
            "to": link.to_node,
            "protocol": cls._transport_protocol(link),
            "port": link.port,
        }

    def _private_ip(self, link: SystemLink, endpoint: str, workspaces: dict[str, Workspace]) -> str:
        node_id = link.from_node if endpoint == "from" else link.to_node
        workspace = workspaces.get(node_id)
        if workspace is None:
            raise GarDomainError(f"node {node_id} のworkspaceを解決できません")
        private_ip = workspace.simulation_private_ip
        if not private_ip:
            raise GarDomainError(f"node {node_id} のprivate_ipが未設定です")
        return private_ip
