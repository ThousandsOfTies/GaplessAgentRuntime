from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def load_server_module():
    path = Path(__file__).resolve().parents[1] / "tools" / "gar-mcp" / "server.py"
    spec = importlib.util.spec_from_file_location("gar_mcp_server", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load Gapless Agent Runtime MCP server")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server = load_server_module()


class GarMcpTest(unittest.TestCase):
    def test_tools_list_contains_visible_terminal_tool(self) -> None:
        response = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})

        tool_names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertIn("run_in_visible_terminal", tool_names)
        self.assertIn("list_terminal_status", tool_names)
        self.assertIn("get_terminal_status", tool_names)

    def test_empty_mcp_collections_and_ping_are_supported(self) -> None:
        expected_results = {
            "resources/list": {"resources": []},
            "prompts/list": {"prompts": []},
            "ping": {},
        }

        for request_id, (method, expected_result) in enumerate(expected_results.items(), start=1):
            with self.subTest(method=method):
                response = server.handle_request({"jsonrpc": "2.0", "id": request_id, "method": method})
                self.assertEqual(expected_result, response["result"])

    def test_notifications_are_ignored_without_a_response(self) -> None:
        for method in (
            "notifications/initialized",
            "notifications/cancelled",
            "notifications/progress",
            "notifications/future-extension",
        ):
            with self.subTest(method=method):
                response = server.handle_request({"jsonrpc": "2.0", "method": method, "params": {}})
                self.assertIsNone(response)

    def test_invalid_request_and_params_return_json_rpc_errors(self) -> None:
        invalid_request = server.handle_request(["not", "an", "object"])
        invalid_params = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": [],
            }
        )

        self.assertEqual(-32600, invalid_request["error"]["code"])
        self.assertEqual(-32602, invalid_params["error"]["code"])

    def test_main_continues_after_malformed_json(self) -> None:
        standard_input = io.StringIO('not json\n{"jsonrpc":"2.0","id":3,"method":"ping"}\n')
        standard_output = io.StringIO()

        with (
            mock.patch.object(server.sys, "stdin", standard_input),
            mock.patch.object(server.sys, "stdout", standard_output),
        ):
            self.assertEqual(0, server.main())

        responses = [json.loads(line) for line in standard_output.getvalue().splitlines()]
        self.assertEqual(-32700, responses[0]["error"]["code"])
        self.assertEqual({}, responses[1]["result"])

    def test_run_in_visible_terminal_creates_request_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
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

    def test_get_terminal_status_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            outside_status = tmp_path / "outside.json"
            outside_status.write_text('{"secret": true}\n', encoding="utf-8")
            with (
                mock.patch.object(server, "REQUEST_DIR", tmp_path / ".gar" / "terminal-requests"),
                mock.patch.object(server, "STATUS_DIR", tmp_path / ".gar" / "terminal-status"),
            ):
                with self.assertRaisesRegex(ValueError, "id"):
                    server.get_terminal_status({"id": "../../outside"})


if __name__ == "__main__":
    unittest.main()
