"""`gar shim`: build local simulation/device shim artifacts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.gar_lib.config import PROJECT_ROOT, load_config


def run_shim_command(command: str, *, json_output: bool = False) -> int:
    if command != "build":
        print(f"gar shim: unknown command: {command}")
        return 1

    config = load_config()
    selected_simulation = config.get("selected_providers", {}).get("simulation")
    selected_target = config.get("selected_target")

    if selected_simulation == "wokwi" and selected_target == "esp32":
        return run_wokwi_shim_build(json_output=json_output)

    print(
        "gar shim build: 現在の setup では対応する shim build が見つかりません。\n"
        f"  target: {selected_target or '(未設定)'}\n"
        f"  simulation: {selected_simulation or '(未設定)'}\n"
        "  Run `gar setup` and choose ESP32 / M5Stack + Wokwi."
    )
    return 1


def run_wokwi_shim_build(*, json_output: bool = False) -> int:
    client_dir = PROJECT_ROOT.parent / "gar-vibe-ui" / "vibe-remote" / "m5stickc-client"
    if not (client_dir / "Makefile").is_file():
        print(f"gar shim build: Wokwi client Makefile が見つかりません: {client_dir}")
        return 1

    env = os.environ.copy()
    platformio_bin = Path.home() / ".venvs" / "platformio" / "bin"
    env["PATH"] = f"{platformio_bin}:{Path.home() / 'bin'}:{env.get('PATH', '')}"

    if not json_output:
        print("gar shim build: Wokwi firmware build を実行します。")
        print(f"  cwd: {client_dir}")
        print("  command: make wokwi-build")

    result = subprocess.run(
        ["make", "wokwi-build"],
        cwd=client_dir,
        env=env,
        stdout=sys.stderr if json_output else None,
        stderr=sys.stderr if json_output else None,
    )
    if json_output:
        print(
            json.dumps(
                {
                    "command": "shim build",
                    "provider": "wokwi",
                    "target": "esp32",
                    "cwd": str(client_dir),
                    "delegated_command": "make wokwi-build",
                    "ok": result.returncode == 0,
                    "exit_code": result.returncode,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return result.returncode
