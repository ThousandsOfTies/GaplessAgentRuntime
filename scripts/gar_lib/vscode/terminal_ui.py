"""Shared UI helpers: ANSI color codes, styled output, safe input prompts."""

from __future__ import annotations

import os
import sys

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
BLUE = "\033[34m"


def _use_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def style(text: str, *codes: str) -> str:
    if not _use_color() or not codes:
        return text
    return "".join(codes) + text + RESET


def safe_input(prompt: str, *, default_on_eof: str = "q") -> str:
    try:
        return input(prompt).strip()
    except (EOFError, OSError):
        print()
        print(style("入力を受け取れないため、対話処理を終了します。", YELLOW))
        return default_on_eof
    except KeyboardInterrupt:
        print()
        print(style("入力が中断されたため、対話処理を終了します。", YELLOW))
        return default_on_eof
