"""Vibe Remote virtual device provider.

M5Stack 実機や Wokwi/Renode の前段として、ファイル backed な疑似デバイスを
simulation tool list に載せる。実体は gar-vibe-ui 側の
`vibe-remote/scripts/virtual-device.js`。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from scripts.gar_lib.environments.base import CommandStatus, DevEnvironment

DEFAULT_SCRIPT = (
    Path.home()
    / "Yurufuwa"
    / "gar-vibe-ui"
    / "vibe-remote"
    / "scripts"
    / "virtual-device.js"
)
DEFAULT_NODE_SH = (
    Path.home()
    / "Yurufuwa"
    / "gar-vibe-ui"
    / "vibe-remote"
    / "scripts"
    / "node.sh"
)


class VibeRemoteVirtualDeviceEnvironment(DevEnvironment):
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
        return (
            "Vibe Remote virtual device を使うには Node.js が必要です。\n"
            "`vibe-remote/scripts/node.sh` が使える場合は自動でそれを使います。\n"
            "依存が未導入の場合は次を実行してください:\n"
            "  cd ~/Yurufuwa/gar-vibe-ui/vibe-remote\n"
            "  npm install"
        )

    @classmethod
    def list_instances(cls) -> int:
        script = _script_path()
        print(f"script: {script}")
        print(f"dev:    {_dev_dir()}")
        print("run:    gar setup でこの provider を選び、下記を実行:")
        print(
            "        VIBE_REMOTE_TOKEN=... "
            f"{_node_command()} {script} --dev={_dev_dir()}"
        )
        return 0 if script.exists() else 1

    @classmethod
    def shell(cls, target: str | None = None) -> int:
        script = _script_path()
        if not script.exists():
            print(f"virtual device script not found: {script}")
            return 1

        token = os.environ.get("VIBE_REMOTE_TOKEN", "")
        if not token:
            print("VIBE_REMOTE_TOKEN is required.")
            print("VS Code で `Vibe Remote: 接続トークンを表示` を実行して設定してください。")
            return 1

        argv = [
            _node_command(),
            str(script),
            f"--dev={_dev_dir()}",
        ]
        return subprocess.run(argv, check=False).returncode

    @classmethod
    def interactive_shell_script(cls, target: str) -> str:
        script = _script_path()
        dev_dir = _dev_dir()
        node_command = _node_command()
        return f"""#!/usr/bin/env bash
set -euo pipefail

if [ -z "${{VIBE_REMOTE_TOKEN:-}}" ]; then
  echo "VIBE_REMOTE_TOKEN is required." >&2
  echo "Run 'Vibe Remote: 接続トークンを表示' in VS Code and export it first." >&2
  exit 1
fi

exec {node_command} {script} --dev={dev_dir}
"""


def _script_path() -> Path:
    return Path(os.environ.get("VIBE_REMOTE_DEVICE_SCRIPT", str(DEFAULT_SCRIPT))).expanduser()


def _dev_dir() -> str:
    return os.environ.get("VIBE_REMOTE_DEV", "/tmp/gar-vibe-remote-device")


def _node_command() -> str:
    configured = os.environ.get("VIBE_REMOTE_NODE")
    if configured:
        return configured
    node_sh = _node_sh_path()
    if node_sh.exists():
        return str(node_sh)
    return _find_node() or "node"


def _node_sh_path() -> Path:
    return Path(os.environ.get("VIBE_REMOTE_NODE_SH", str(DEFAULT_NODE_SH))).expanduser()


def _find_node() -> str | None:
    from shutil import which

    return which("node")
