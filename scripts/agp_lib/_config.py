"""Project paths, config IO, and EC2 host helpers."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

CONFIG_PATH = Path(".agp") / "config.json"

# scripts/agp_lib/_config.py -> scripts/agp_lib -> scripts -> repo root
PROJECT_ROOT = Path(__file__).resolve().parents[2]

VSCODE_EXT_NAME = "agentcockpit-terminal-bridge"
VSCODE_EXT_VERSION = "0.0.1"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return default_config()

    try:
        text = CONFIG_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        print(
            f"agp: warning: failed to read {CONFIG_PATH}: {exc}; using defaults",
            file=sys.stderr,
        )
        return default_config()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        print(
            f"agp: warning: {CONFIG_PATH} is not valid JSON ({exc}); using defaults. "
            "Run `agp setup` to recreate it.",
            file=sys.stderr,
        )
        return default_config()

    if not isinstance(data, dict):
        print(
            f"agp: warning: {CONFIG_PATH} root must be an object; using defaults",
            file=sys.stderr,
        )
        return default_config()

    selected_providers = data.get("selected_providers")
    if not isinstance(selected_providers, dict):
        selected_providers = {}

    ec2 = data.get("ec2")
    ec2_host = None
    if isinstance(ec2, dict) and isinstance(ec2.get("host"), str):
        ec2_host = ec2["host"]

    return {
        "selected_providers": {
            str(category_id): str(provider_id)
            for category_id, provider_id in selected_providers.items()
        },
        "ec2": {"host": ec2_host or "vibecode-graviton"},
    }


def save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    # Write atomically: write to a sibling temp file, fsync, then os.replace.
    # Avoids leaving CONFIG_PATH empty/half-written on crash or Ctrl-C.
    fd, tmp_name = tempfile.mkstemp(
        prefix=CONFIG_PATH.name + ".",
        suffix=".tmp",
        dir=str(CONFIG_PATH.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # fsync is a best-effort durability hint; some filesystems reject it.
                pass
        os.replace(tmp_name, CONFIG_PATH)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def default_config() -> dict:
    return {
        "selected_providers": {},
        "ec2": {"host": "vibecode-graviton"},
    }


def default_ec2_host(config: dict) -> str:
    ec2 = config.get("ec2")
    if isinstance(ec2, dict) and isinstance(ec2.get("host"), str) and ec2["host"]:
        return ec2["host"]
    return "vibecode-graviton"


def set_default_ec2_host(config: dict, host: str) -> None:
    ec2 = config.setdefault("ec2", {})
    if not isinstance(ec2, dict):
        ec2 = {}
        config["ec2"] = ec2
    ec2["host"] = host
