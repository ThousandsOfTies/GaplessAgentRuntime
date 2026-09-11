"""Output mode shared by CLI boundaries and child-process adapters."""

import json
from collections.abc import Mapping
from contextvars import ContextVar

JSON_OUTPUT = ContextVar("gar_json_output", default=False)
JSON_RESULT: ContextVar[dict[str, object] | None] = ContextVar("gar_json_result", default=None)


def emit_json(payload: Mapping[str, object]) -> None:
    """Keep a structured result separate from progress and child-process output."""
    if JSON_OUTPUT.get():
        JSON_RESULT.set(dict(payload))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
