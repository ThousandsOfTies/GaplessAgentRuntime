"""Terminal Bridge VS Code extension install (``tools/vscode-gar``)."""

from __future__ import annotations

import shutil
from pathlib import Path

from scripts.gar_lib.config import (
    PROJECT_ROOT,
    VSCODE_EXT_NAME,
    VSCODE_EXT_VERSION,
)


def installed_vscode_terminal_bridge_path() -> Path | None:
    extension_dir_name = f"{VSCODE_EXT_NAME}-{VSCODE_EXT_VERSION}"
    candidates = (
        Path.home() / ".vscode-server" / "extensions" / extension_dir_name,
        Path.home() / ".vscode" / "extensions" / extension_dir_name,
    )

    for path in candidates:
        if path.exists():
            return path

    return None


def install_vscode_terminal_bridge() -> int:
    src = PROJECT_ROOT / "tools" / "vscode-gar"
    dest = (
        Path.home()
        / ".vscode-server"
        / "extensions"
        / f"{VSCODE_EXT_NAME}-{VSCODE_EXT_VERSION}"
    )
    try:
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest)
    except OSError:
        return 1
    return 0
