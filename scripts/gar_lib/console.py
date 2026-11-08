"""Consistent Unicode output for Windows consoles and redirected launchers."""

from __future__ import annotations

import sys


def configure_output() -> None:
    """Keep Japanese CLI output readable when Windows redirects a legacy code page."""

    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
