"""Own only the SSH Bridge tunnels started for one local system file."""

from __future__ import annotations

import hashlib
import os
import socket
import time
from collections.abc import Collection
from pathlib import Path

import psutil

from scripts.gar_lib.commands.workspace_resolver import resolve_workspace
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.simulation.runtime.process import LocalProcessChannel, ManagedProcess, ProcessStateStore
from scripts.gar_lib.system.model import SystemTopology


class SystemConnections:
    def __init__(self, file: str | Path, *, directory: Path | None = None, channel=None, resolver=resolve_workspace):
        self.owner = os.path.normcase(str(Path(file).expanduser().resolve()))
        key = hashlib.sha256(self.owner.encode("utf-8")).hexdigest()
        root = directory or Path(
            os.environ.get("GAR_PORT_FORWARD_STATE_DIR", Path.home() / ".cache" / "GaplessAgentRuntime")
        )
        self.store = ProcessStateStore(root / "systems" / f"{key}.json")
        self.channel = channel or LocalProcessChannel()
        self.resolver = resolver

    def _read(self) -> dict:
        state = self.store.read()
        if self.store.path.exists() and (
            state.get("schema_version") != 1
            or state.get("owner") != self.owner
            or not isinstance(state.get("nodes"), dict)
        ):
            raise GarDomainError("system connection stateが不正です。接続processは変更していません。")
        return state or {"schema_version": 1, "owner": self.owner, "name": Path(self.owner).stem, "nodes": {}}

    def _owned(self, entry: dict) -> ManagedProcess | None:
        process = ManagedProcess.from_state(entry)
        # Old or incomplete PID-only state must never authorize termination.
        if process is None or process.start_time_ticks is None or not self.channel.owns(process):
            return None
        return process

    def _plan(self, topology: SystemTopology, ports: dict[str, int]) -> dict[str, dict]:
        unknown = set(ports) - set(topology.nodes)
        if unknown:
            raise GarDomainError(f"--port のnodeがsystemにありません: {', '.join(sorted(unknown))}")
        executable = os.environ.get("GAR_SSH_EXECUTABLE") or self.channel.find_executable("ssh")
        if not executable:
            raise GarDomainError("system connectにはSSH clientが必要です")
        plan = {}
        used = set()
        for node_id in topology.order:
            node = topology.nodes[node_id]
            workspace = self.resolver(node.workspace)
            if node.environment != "sim" or workspace.selected_environments.simulator != "ssh_remote":
                raise GarDomainError(f"node {node_id}: system connectはSSH Remote SimulationのBridgeに対応しています")
            host = workspace.simulation_ssh_host
            if not host or host.startswith("-") or any(character.isspace() for character in host):
                raise GarDomainError(f"node {node_id}: Simulation SSH hostが未設定または不正です")
            port = ports.get(node_id, workspace.simulation_bridge_port)
            if type(port) is not int or not 1 <= port <= 65535:
                raise GarDomainError(
                    f"node {node_id}: --port {node_id}=PORT またはsimulation_host.bridge_portを指定してください"
                )
            if port in used:
                raise GarDomainError(f"Bridgeのlocal portが重複しています: {port}")
            used.add(port)
            argv = (
                executable,
                "-F",
                str(Path.home() / ".ssh" / "config"),
                "-N",
                "-n",
                "-T",
                "-o",
                "BatchMode=yes",
                "-o",
                "ExitOnForwardFailure=yes",
                "-o",
                "ConnectTimeout=10",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                "ServerAliveInterval=15",
                "-o",
                "ServerAliveCountMax=2",
                "-L",
                f"127.0.0.1:{port}:127.0.0.1:8080",
                host,
            )
            plan[node_id] = {
                "argv": list(argv),
                "port": port,
                "url": f"http://127.0.0.1:{port}",
                "workspace": node.workspace,
            }
        return plan

    @staticmethod
    def _require_free(port: int) -> None:
        try:
            with socket.socket() as probe:
                # Match the SSH loopback bind, without SO_REUSEADDR.
                probe.bind(("127.0.0.1", port))
        except OSError as error:
            raise GarDomainError(f"local port {port} は使用中です。既存の接続は変更していません。") from error

    def _ready(self, process: ManagedProcess, port: int) -> bool:
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if not self.channel.owns(process):
                return False
            try:
                listeners = psutil.Process(process.pid).net_connections(kind="tcp")
                if any(
                    item.status == psutil.CONN_LISTEN and item.laddr.ip == "127.0.0.1" and item.laddr.port == port
                    for item in listeners
                ):
                    return self.channel.owns(process)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return False
            time.sleep(0.05)
        return False

    def _stop(self, entry: dict) -> bool:
        recorded = ManagedProcess.from_state(entry)
        if recorded is not None and recorded.start_time_ticks is None:
            return False
        process = self._owned(entry)
        if process is None:
            return True
        self.channel.terminate_group(process)
        deadline = time.monotonic() + 3
        while self.channel.owns(process) and time.monotonic() < deadline:
            time.sleep(0.05)
        return not self.channel.owns(process)

    def connect(self, topology: SystemTopology, ports: dict[str, int]) -> dict:
        # Resolve and validate all nodes before opening the first tunnel.
        plan = self._plan(topology, ports)
        with self.store.locked():
            state = self._read()
            entries = state["nodes"]
            for node_id, entry in entries.items():
                if self._owned(entry) and (
                    node_id not in plan
                    or entry.get("argv") != plan[node_id]["argv"]
                    or entry.get("workspace") != plan[node_id]["workspace"]
                ):
                    raise GarDomainError(
                        "このsystemには異なる設定の接続があります。system disconnect後に再接続してください。"
                    )
            for node_id, config in plan.items():
                if not self._owned(entries.get(node_id, {})):
                    self._require_free(config["port"])
            created = []
            failures = []
            state["name"] = topology.name
            try:
                for node_id, config in plan.items():
                    if self._owned(entries.get(node_id, {})):
                        continue
                    process = self.channel.start(
                        tuple(config["argv"]),
                        cwd=Path.home(),
                        log_path=self.store.path.with_name(f"{self.store.path.stem}-{node_id}.log"),
                    )
                    entries[node_id] = {**config, **process.to_state()}
                    created.append(node_id)
                    # Persist even before readiness, so interrupted connect can be disconnected.
                    self.store.write(state)
                    if process.start_time_ticks is None or not self._ready(process, config["port"]):
                        raise GarDomainError(f"node {node_id}: Bridge tunnelの開始を確認できません")
            except Exception as error:
                failures.append({"node": "system", "action": "connect", "error": str(error)})
                for node_id in reversed(created):
                    if self._stop(entries[node_id]):
                        del entries[node_id]
                    else:
                        failures.append({"node": node_id, "action": "rollback", "error": "tunnel停止を確認できません"})
            self.store.write(state)
            return self._report("connect", state, failures)

    def disconnect(self) -> dict:
        with self.store.locked():
            state = self._read()
            failures = []
            for node_id in reversed(tuple(state["nodes"])):
                if self._stop(state["nodes"][node_id]):
                    del state["nodes"][node_id]
                else:
                    failures.append({"node": node_id, "action": "disconnect", "error": "tunnel停止を確認できません"})
                self.store.write(state)
            return self._report("disconnect", state, failures)

    def status(self) -> dict:
        state = self._read()
        failures = [
            {"node": node_id, "action": "status", "error": "記録したBridge tunnelは稼働していません"}
            for node_id, entry in state["nodes"].items()
            if not self._owned(entry)
        ]
        return self._report("status", state, failures)

    def urls(self, topology: SystemTopology | None = None, *, overridden: Collection[str] = ()) -> dict[str, str]:
        urls = {}
        for node_id, entry in self._read()["nodes"].items():
            if node_id in overridden or not self._owned(entry):
                continue
            if topology is not None:
                node = topology.nodes.get(node_id)
                if node is None:
                    continue
                workspace = self.resolver(node.workspace)
                if (
                    node.environment != "sim"
                    or workspace.selected_environments.simulator != "ssh_remote"
                    or entry.get("workspace") != node.workspace
                    or workspace.simulation_ssh_host != entry["argv"][-1]
                ):
                    raise GarDomainError(
                        f"node {node_id}: 接続時から設定が変わっています。system disconnect / connectを実行してください。"
                    )
            urls[node_id] = entry["url"]
        return urls

    def _report(self, action: str, state: dict, failures: list[dict]) -> dict:
        return {
            "schema_version": 1,
            "command": f"system.{action}",
            "subject": "connections",
            "name": state["name"],
            "ok": not failures,
            "exit_code": int(bool(failures)),
            "nodes": [
                {"id": node_id, "url": entry["url"], "state": "connected" if self._owned(entry) else "stopped"}
                for node_id, entry in state["nodes"].items()
            ],
            "failures": failures,
        }
