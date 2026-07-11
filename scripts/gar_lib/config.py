"""Project paths, config IO, and EC2 host helpers."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# scripts/gar_lib/config.py -> scripts/gar_lib -> scripts -> repo root
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# GAR's control-plane settings belong to the Runtime checkout, never to the
# current product workspace from which the command happened to be invoked.
CONFIG_PATH = PROJECT_ROOT / ".gar" / "config.json"

VSCODE_EXT_NAME = "gar-terminal-bridge"
VSCODE_EXT_VERSION = "0.0.1"

DEFAULT_EC2_HOST = "vibecode-graviton"
DEFAULT_EC2_INSTANCE_ID = "i-031e0e5f5f1325ddc"
DEFAULT_EC2_REGION = "ap-southeast-2"
_ACTIVE_WORKSPACE_ROOT: str | None = None


def set_active_workspace_root(root: str | None) -> None:
    """Select the workspace whose settings subsequent config calls use."""
    global _ACTIVE_WORKSPACE_ROOT
    _ACTIVE_WORKSPACE_ROOT = root


def _workspace_entries(data: dict) -> list[dict]:
    raw_entries = data.get("workspaces")
    if not isinstance(raw_entries, list):
        return []
    entries: list[dict] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            continue
        root = raw_entry.get("root")
        if not isinstance(root, str) or not root:
            continue
        entry = dict(raw_entry)
        entry["root"] = str(Path(root).expanduser().resolve())
        entries.append(entry)
    return entries


def _select_workspace_entry(entries: list[dict]) -> dict | None:
    requested_root = _ACTIVE_WORKSPACE_ROOT or os.environ.get("GAR_WORKSPACE_ROOT")
    if requested_root:
        resolved = str(Path(requested_root).expanduser().resolve())
        return next((entry for entry in entries if entry["root"] == resolved), None)

    current = Path.cwd().resolve()
    matching = [
        entry
        for entry in entries
        if current == Path(entry["root"]).resolve()
        or current.is_relative_to(Path(entry["root"]).resolve())
    ]
    if matching:
        return max(matching, key=lambda entry: len(entry["root"]))
    if len(entries) == 1:
        return entries[0]
    return None


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return default_config()

    try:
        text = CONFIG_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        print(
            f"gar: warning: failed to read {CONFIG_PATH}: {exc}; using defaults",
            file=sys.stderr,
        )
        return default_config()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        print(
            f"gar: warning: {CONFIG_PATH} is not valid JSON ({exc}); using defaults. "
            "Run `gar setup` to recreate it.",
            file=sys.stderr,
        )
        return default_config()

    if not isinstance(data, dict):
        print(
            f"gar: warning: {CONFIG_PATH} root must be an object; using defaults",
            file=sys.stderr,
        )
        return default_config()

    entries = _workspace_entries(data)
    selected_entry = _select_workspace_entry(entries)
    if selected_entry is None:
        return default_config(workspaces=entries)
    data = selected_entry

    selected_providers = data.get("selected_providers")
    if not isinstance(selected_providers, dict):
        selected_providers = {}

    selected_target = data.get("selected_target")
    if not isinstance(selected_target, str) or not selected_target:
        selected_target = None

    ec2 = data.get("ec2")
    ec2_host = None
    ec2_instance_id = None
    ec2_region = None
    ec2_repo_dir = None
    if isinstance(ec2, dict):
        if isinstance(ec2.get("host"), str):
            ec2_host = ec2["host"]
        if isinstance(ec2.get("instance_id"), str):
            ec2_instance_id = ec2["instance_id"]
        if isinstance(ec2.get("region"), str):
            ec2_region = ec2["region"]
        if isinstance(ec2.get("repo_dir"), str):
            ec2_repo_dir = ec2["repo_dir"]

    usb = data.get("usb")
    usb_busid = None
    if isinstance(usb, dict) and isinstance(usb.get("busid"), str):
        usb_busid = usb["busid"]

    adb = data.get("adb")
    adb_exe_path = None
    adb_version = None
    if isinstance(adb, dict):
        if isinstance(adb.get("exe_path"), str) and adb["exe_path"]:
            adb_exe_path = adb["exe_path"]
        if isinstance(adb.get("version"), str) and adb["version"]:
            adb_version = adb["version"]

    esp32 = data.get("esp32")
    esp32_port = None
    if isinstance(esp32, dict) and isinstance(esp32.get("port"), str) and esp32["port"]:
        esp32_port = esp32["port"]

    return {
        "root": data["root"],
        "workspaces": entries,
        **({"selected_target": selected_target} if selected_target else {}),
        "selected_providers": {
            str(category_id): str(provider_id)
            for category_id, provider_id in selected_providers.items()
        },
        "ec2": {
            "host": ec2_host or DEFAULT_EC2_HOST,
            "instance_id": ec2_instance_id or DEFAULT_EC2_INSTANCE_ID,
            "region": ec2_region or DEFAULT_EC2_REGION,
            **({"repo_dir": ec2_repo_dir} if ec2_repo_dir else {}),
        },
        **({"usb": {"busid": usb_busid}} if usb_busid else {}),
        **({"esp32": {"port": esp32_port}} if esp32_port else {}),
        **(
            {
                "adb": {
                    **({"exe_path": adb_exe_path} if adb_exe_path else {}),
                    **({"version": adb_version} if adb_version else {}),
                }
            }
            if (adb_exe_path or adb_version)
            else {}
        ),
    }


def save_config(config: dict) -> None:
    entries = _workspace_entries(config)
    root = config.get("root")
    if isinstance(root, str) and root and any(entry["root"] == root for entry in entries):
        active = {
            key: value
            for key, value in config.items()
            if key not in {"root", "workspaces"}
        }
        active["root"] = root
        entries = [entry for entry in entries if entry["root"] != root]
        entries.append(active)
    payload_config = {"workspaces": entries}
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(payload_config, ensure_ascii=False, indent=2) + "\n"
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


def default_config(*, workspaces: list[dict] | None = None) -> dict:
    return {
        "workspaces": workspaces or [],
        "selected_providers": {},
        "ec2": {
            "host": DEFAULT_EC2_HOST,
            "instance_id": DEFAULT_EC2_INSTANCE_ID,
            "region": DEFAULT_EC2_REGION,
        },
    }


def default_ec2_host(config: dict) -> str:
    ec2 = config.get("ec2")
    if isinstance(ec2, dict) and isinstance(ec2.get("host"), str) and ec2["host"]:
        return ec2["host"]
    return DEFAULT_EC2_HOST


def default_ec2_instance_id(config: dict) -> str:
    ec2 = config.get("ec2")
    if isinstance(ec2, dict) and isinstance(ec2.get("instance_id"), str) and ec2["instance_id"]:
        return ec2["instance_id"]
    return DEFAULT_EC2_INSTANCE_ID


def default_ec2_region(config: dict) -> str:
    ec2 = config.get("ec2")
    if isinstance(ec2, dict) and isinstance(ec2.get("region"), str) and ec2["region"]:
        return ec2["region"]
    return DEFAULT_EC2_REGION


def ec2_repo_dir(config: dict) -> str | None:
    ec2 = config.get("ec2")
    if isinstance(ec2, dict) and isinstance(ec2.get("repo_dir"), str) and ec2["repo_dir"]:
        return ec2["repo_dir"]
    return None


def saved_usb_busid(config: dict) -> str | None:
    usb = config.get("usb")
    if isinstance(usb, dict) and isinstance(usb.get("busid"), str) and usb["busid"]:
        return usb["busid"]
    return None


def set_saved_usb_busid(config: dict, busid: str) -> None:
    usb = config.setdefault("usb", {})
    if not isinstance(usb, dict):
        usb = {}
        config["usb"] = usb
    usb["busid"] = busid


def saved_esp32_serial_port(config: dict) -> str | None:
    esp32 = config.get("esp32")
    if isinstance(esp32, dict) and isinstance(esp32.get("port"), str) and esp32["port"]:
        return esp32["port"]
    return None


def set_saved_esp32_serial_port(config: dict, port: str) -> None:
    esp32 = config.setdefault("esp32", {})
    if not isinstance(esp32, dict):
        esp32 = {}
        config["esp32"] = esp32
    esp32["port"] = port


def saved_workspace_roots(config: dict) -> list[str]:
    return [entry["root"] for entry in _workspace_entries(config)]


def set_saved_workspace_roots(config: dict, roots: list[str]) -> None:
    old_entries = {entry["root"]: entry for entry in _workspace_entries(config)}
    config["workspaces"] = [
        old_entries.get(root, {"root": root})
        for root in dict.fromkeys(roots)
    ]


def saved_adb_exe(config: dict) -> str | None:
    adb = config.get("adb")
    if isinstance(adb, dict) and isinstance(adb.get("exe_path"), str) and adb["exe_path"]:
        return adb["exe_path"]
    return None


def set_saved_adb_exe(config: dict, exe_path: str, *, version: str | None = None) -> None:
    adb = config.setdefault("adb", {})
    if not isinstance(adb, dict):
        adb = {}
        config["adb"] = adb
    adb["exe_path"] = exe_path
    if version:
        adb["version"] = version


def set_default_ec2_host(config: dict, host: str) -> None:
    ec2 = config.setdefault("ec2", {})
    if not isinstance(ec2, dict):
        ec2 = {}
        config["ec2"] = ec2
    ec2["host"] = host


def set_default_ec2_instance_id(config: dict, instance_id: str) -> None:
    ec2 = config.setdefault("ec2", {})
    if not isinstance(ec2, dict):
        ec2 = {}
        config["ec2"] = ec2
    ec2["instance_id"] = instance_id


def set_default_ec2_region(config: dict, region: str) -> None:
    ec2 = config.setdefault("ec2", {})
    if not isinstance(ec2, dict):
        ec2 = {}
        config["ec2"] = ec2
    ec2["region"] = region
