"""Preserve interactive output, or capture child output for a single JSON result."""

from __future__ import annotations

import subprocess
import sys
import tempfile

from scripts.gar_lib.core.output import JSON_OUTPUT


def run_displayed(argv, *, runner=None, **options):
    execute = runner or subprocess.run
    if not JSON_OUTPUT.get() or options.get("capture_output") or "stdout" in options or "stderr" in options:
        return execute(argv, **options)
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        result = execute(argv, stdout=output, stderr=errors, **options)
        for stream, destination in ((output, sys.stdout), (errors, sys.stderr)):
            stream.seek(0)
            text = stream.read().decode("utf-8", errors="replace")
            if text:
                print(text, end="", file=destination)
    return result
