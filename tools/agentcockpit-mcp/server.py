#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid


ROOT = Path(__file__).resolve().parents[2]
AGP_DIR = ROOT / ".agp"
REQUEST_DIR = AGP_DIR / "terminal-requests"
STATUS_DIR = AGP_DIR / "terminal-status"


TOOLS = [
    {
        "name": "run_in_visible_terminal",
        "description": (
            "Create an AgentCockpit request that the VSCode extension runs in a "
            "visible integrated terminal for human sudo/auth input."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to run in the visible terminal.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory. Defaults to the AgentCockpit repo root.",
                },
                "title": {
                    "type": "string",
                    "description": "VSCode terminal title.",
                    "default": "AgentCockpit User Action",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "list_terminal_status",
        "description": "List AgentCockpit terminal request status files.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_terminal_status",
        "description": "Read one AgentCockpit terminal request status by id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Terminal request id.",
                }
            },
            "required": ["id"],
        },
    },
]


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
            response = handle_request(request)
        except Exception as exc:  # Keep the MCP process alive on bad input.
            response = error_response(None, -32603, str(exc))

        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)

    return 0


def handle_request(request: dict) -> dict | None:
    method = request.get("method")
    request_id = request.get("id")

    if method == "initialize":
        return result_response(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "agentcockpit-mcp",
                    "version": "0.0.1",
                },
            },
        )

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return result_response(request_id, {"tools": TOOLS})

    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        return result_response(request_id, call_tool(name, arguments))

    return error_response(request_id, -32601, f"Unknown method: {method}")


def call_tool(name: str, arguments: dict) -> dict:
    if name == "run_in_visible_terminal":
        return text_result(create_terminal_request(arguments))
    if name == "list_terminal_status":
        return text_result(json.dumps(list_terminal_status(), ensure_ascii=False, indent=2))
    if name == "get_terminal_status":
        return text_result(json.dumps(get_terminal_status(arguments), ensure_ascii=False, indent=2))

    return {
        "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
        "isError": True,
    }


def create_terminal_request(arguments: dict) -> str:
    command = str(arguments.get("command", "")).strip()
    if not command:
        raise ValueError("command is required")
    if len(command) > 4000:
        raise ValueError("command exceeds 4000 character limit")
    if "\x00" in command:
        raise ValueError("command must not contain NUL bytes")

    title = str(arguments.get("title") or "AgentCockpit User Action")
    if len(title) > 200:
        raise ValueError("title exceeds 200 character limit")

    raw_cwd = arguments.get("cwd")
    cwd = Path(str(raw_cwd)).resolve() if raw_cwd else ROOT
    try:
        cwd.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError(
            f"cwd must be inside the AgentCockpit repository ({ROOT}); got {cwd}"
        ) from exc

    request_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    request_id = f"{request_id}-{uuid.uuid4().hex[:8]}"

    REQUEST_DIR.mkdir(parents=True, exist_ok=True)
    request_path = REQUEST_DIR / f"{request_id}.json"
    request = {
        "id": request_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "cwd": str(cwd),
        "command": command,
    }
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return json.dumps(
        {
            "id": request_id,
            "request_path": str(request_path),
            "message": "Terminal request created. The VSCode extension will run it.",
        },
        ensure_ascii=False,
        indent=2,
    )


def list_terminal_status() -> list[dict]:
    if not STATUS_DIR.exists():
        return []

    statuses: list[dict] = []
    for path in sorted(STATUS_DIR.glob("*.json")):
        try:
            statuses.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            statuses.append({"id": path.stem, "status": "invalid-json"})
    return statuses


def get_terminal_status(arguments: dict) -> dict:
    request_id = str(arguments.get("id", "")).strip()
    if not request_id:
        raise ValueError("id is required")

    status_path = STATUS_DIR / f"{request_id}.json"
    if not status_path.exists():
        return {"id": request_id, "status": "unknown"}

    return json.loads(status_path.read_text(encoding="utf-8"))


def text_result(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def result_response(request_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_response(request_id, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


if __name__ == "__main__":
    raise SystemExit(main())
