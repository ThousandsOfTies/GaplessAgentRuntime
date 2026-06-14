from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def load_server_module():
    path = Path(__file__).resolve().parents[1] / "tools" / "agentcockpit-mcp" / "server.py"
    spec = importlib.util.spec_from_file_location("gar_mcp_server", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load Gapless Agent Runtime MCP server")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server = load_server_module()


class GarMcpTest(unittest.TestCase):
    def test_tools_list_contains_visible_terminal_tool(self) -> None:
        response = server.handle_request(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        )

        tool_names = {
            tool["name"]
            for tool in response["result"]["tools"]
        }
        self.assertIn("run_in_visible_terminal", tool_names)
        self.assertIn("list_terminal_status", tool_names)
        self.assertIn("get_terminal_status", tool_names)

    def test_run_in_visible_terminal_creates_request_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with (
                mock.patch.object(server, "ROOT", tmp_path),
                mock.patch.object(server, "GAR_DIR", tmp_path / ".gar"),
                mock.patch.object(server, "REQUEST_DIR", tmp_path / ".gar" / "terminal-requests"),
            ):
                response = server.call_tool(
                    "run_in_visible_terminal",
                    {
                        "command": "echo hello",
                        "title": "Test",
                        "cwd": str(tmp_path),
                    },
                )

            text = response["content"][0]["text"]
            payload = json.loads(text)
            request_path = Path(payload["request_path"])
            request = json.loads(request_path.read_text(encoding="utf-8"))

            self.assertEqual("echo hello", request["command"])
            self.assertEqual("Test", request["title"])
            self.assertEqual(str(tmp_path), request["cwd"])


if __name__ == "__main__":
    unittest.main()
