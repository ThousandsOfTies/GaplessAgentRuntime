"""Vibe Remote virtual device provider.

M5Stack 実機や Wokwi/Renode の前段として、ファイル backed な疑似デバイスを
simulation tool list に載せる。実体は gar-vibe-ui 側の
`vibe-remote/scripts/virtual-device.js`。
"""

from __future__ import annotations

import os
from pathlib import Path

from scripts.gar_lib.environments.base import CommandStatus, EnvironmentSetupOption

DEFAULT_NODE_SH = (
    Path.home()
    / "Yurufuwa"
    / "gar-vibe-ui"
    / "vibe-remote"
    / "scripts"
    / "node.sh"
)


class VibeRemoteVirtualDeviceEnvironment(EnvironmentSetupOption):
    provider_id = "vibe_remote_device"
    display_name = "Vibe Remote Virtual Device"
    description = (
        "M5Stack の代わりに /tmp 配下の疑似デバイスファイルから "
        "Vibe Remote WebSocket へ状態イベントを送ります"
    )
    display_order = 20
    required_commands = ()

    @classmethod
    def dependency_status(cls) -> list[CommandStatus]:
        node_sh = _node_sh_path()
        if node_sh.exists():
            return [CommandStatus(name=str(node_sh), path=str(node_sh))]
        node_path = _find_node()
        return [CommandStatus(name="node", path=node_path)]

    @classmethod
    def install_hint(cls, missing: list[str]) -> str:
        del missing
        return (
            "Vibe Remote virtual device を使うには Node.js が必要です。\n"
            "`vibe-remote/scripts/node.sh` が使える場合は自動でそれを使います。\n"
            "依存が未導入の場合は次を実行してください:\n"
            "  cd ~/Yurufuwa/gar-vibe-ui/vibe-remote\n"
            "  npm install"
        )


def _node_sh_path() -> Path:
    return Path(os.environ.get("VIBE_REMOTE_NODE_SH", str(DEFAULT_NODE_SH))).expanduser()


def _find_node() -> str | None:
    from shutil import which

    return which("node")
