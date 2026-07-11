#!/usr/bin/env python3
"""A minimal JSON control plane for a MuJoCo model.

The bridge intentionally understands only physics-level operations.  Product
runners may replace it to expose domain operations such as ``walk-start`` or
``set-gait`` while retaining the same ``/api/state`` and ``/api/command``
entrypoints.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import mujoco
from mujoco import viewer


class Simulation:
    def __init__(self, model_path: Path):
        self.model = mujoco.MjModel.from_xml_path(str(model_path))
        self.data = mujoco.MjData(self.model)
        self.lock = threading.RLock()
        self.running = True

    def step_forever(self) -> None:
        while self.running:
            started = time.monotonic()
            with self.lock:
                mujoco.mj_step(self.model, self.data)
            time.sleep(max(0.0, self.model.opt.timestep - (time.monotonic() - started)))

    def state(self) -> dict[str, Any]:
        with self.lock:
            actuators = {
                mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR, index) or str(index): float(self.data.ctrl[index])
                for index in range(self.model.nu)
            }
            return {
                "ok": True,
                "time": self.data.time,
                "qpos": self.data.qpos.tolist(),
                "qvel": self.data.qvel.tolist(),
                "actuators": actuators,
            }

    def command(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if action == "reset":
                mujoco.mj_resetData(self.model, self.data)
            elif action == "actuator-set":
                actuator = params.get("actuator")
                if not isinstance(actuator, str):
                    raise ValueError("actuator-set requires string params.actuator")
                actuator_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR, actuator)
                if actuator_id < 0:
                    raise ValueError(f"unknown actuator: {actuator}")
                self.data.ctrl[actuator_id] = float(params["value"])
            elif action == "step":
                for _ in range(max(1, int(params.get("count", 1)))):
                    mujoco.mj_step(self.model, self.data)
            else:
                raise ValueError(f"unsupported action: {action}")
        return self.state()


def handler_for(simulation: Simulation):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/api/state":
                self._send(HTTPStatus.OK, simulation.state())
                return
            self._send(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/command":
                self._send(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(content_length).decode("utf-8"))
                result = simulation.command(str(request["action"]), dict(request.get("params", {})))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
                return
            self._send(HTTPStatus.OK, result)

        def log_message(self, format: str, *args: object) -> None:
            del format, args

        def _send(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mjcf", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8081, type=int)
    parser.add_argument("--viewer", action="store_true")
    args = parser.parse_args()

    simulation = Simulation(args.mjcf)
    threading.Thread(target=simulation.step_forever, daemon=True).start()
    server = ThreadingHTTPServer((args.host, args.port), handler_for(simulation))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"MuJoCo bridge listening on http://{args.host}:{args.port}", flush=True)

    try:
        if args.viewer:
            with viewer.launch_passive(simulation.model, simulation.data) as active_viewer:
                while active_viewer.is_running():
                    with simulation.lock:
                        active_viewer.sync()
                    time.sleep(0.01)
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        return 0
    finally:
        simulation.running = False
        server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
