"""`gar sim` output parsing."""
from __future__ import annotations

import json


def parse_sim_diag(raw: str) -> dict:
    """Parse the marker-delimited simulation diag output into a dict.

    Returns ``{"processes": [...], "devices": {...}, "api": ... | None, "ok": bool}``.
    ``ok`` is True when at least one runtime process is alive and the bridge API
    returned parseable JSON.
    """
    section = None
    proc_lines: list[str] = []
    device_lines: list[str] = []
    api_lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped == "@@PROC@@":
            section = "proc"
            continue
        if stripped == "@@DEV@@":
            section = "dev"
            continue
        if stripped == "@@API@@":
            section = "api"
            continue
        if section == "proc":
            if stripped:
                proc_lines.append(stripped)
        elif section == "dev":
            if stripped:
                device_lines.append(stripped)
        elif section == "api":
            api_lines.append(line)

    processes = []
    for line in proc_lines:
        pid, _, cmd = line.partition(" ")
        if pid.isdigit():
            processes.append({"pid": int(pid), "cmd": cmd.strip()})

    devices: dict[str, bool] = {}
    for line in device_lines:
        path, _, flag = line.rpartition(" ")
        if path:
            devices[path] = flag == "1"

    api_text = "\n".join(api_lines).strip()
    api: object | None
    try:
        api = json.loads(api_text) if api_text else None
    except json.JSONDecodeError:
        api = None

    ok = bool(processes) and api is not None
    return {"processes": processes, "devices": devices, "api": api, "ok": ok}

def parse_gpio_runtime_status(raw: str) -> dict:
    section = None
    sections: dict[str, list[str]] = {
        "service": [],
        "device": [],
        "mount": [],
        "configfs": [],
        "gpiochips": [],
    }
    marker_map = {
        "@@SERVICE@@": "service",
        "@@DEVICE@@": "device",
        "@@MOUNT@@": "mount",
        "@@CONFIGFS@@": "configfs",
        "@@GPIOCHIPS@@": "gpiochips",
    }
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped in marker_map:
            section = marker_map[stripped]
            continue
        if section is not None and stripped:
            sections[section].append(stripped)

    service = sections["service"][0] if sections["service"] else "unknown"
    device_path = None
    device_exists = False
    if sections["device"]:
        path, _, flag = sections["device"][0].rpartition(" ")
        device_path = path or None
        device_exists = flag == "1"

    mount_active = bool(sections["mount"] and sections["mount"][0] == "1")
    mount_source = sections["mount"][1] if len(sections["mount"]) > 1 else None
    configfs_active = bool(sections["configfs"] and sections["configfs"][0] == "1")
    live = sections["configfs"][1] if len(sections["configfs"]) > 1 else None
    chip_name = sections["configfs"][2] if len(sections["configfs"]) > 2 else None
    gpiochips = sections["gpiochips"]
    ok = device_exists and configfs_active and live == "1"
    return {
        "service": service,
        "device": {"path": device_path, "exists": device_exists},
        "mount": {"active": mount_active, "source": mount_source},
        "configfs": {"active": configfs_active, "live": live, "chip_name": chip_name},
        "gpiochips": gpiochips,
        "ok": ok,
    }

def parse_gpio_sim_check(raw: str) -> dict:
    """Parse the marker-delimited gpio-sim capability probe output."""
    section = None
    sections: dict[str, list[str]] = {
        "kernel": [],
        "modinfo": [],
        "config": [],
        "configfs": [],
        "dev": [],
    }
    marker_map = {
        "@@KERNEL@@": "kernel",
        "@@MODINFO@@": "modinfo",
        "@@CONFIG@@": "config",
        "@@CONFIGFS@@": "configfs",
        "@@DEV@@": "dev",
    }
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped in marker_map:
            section = marker_map[stripped]
            continue
        if section is not None:
            sections[section].append(line)

    modinfo_lines = [line.strip() for line in sections["modinfo"] if line.strip()]
    modinfo_available = bool(modinfo_lines and modinfo_lines[0] == "1")
    modinfo = modinfo_lines[1:] if modinfo_lines else []
    config_lines = [line.strip() for line in sections["config"] if line.strip()]
    config_mentions_gpio_sim = any(
        "GPIO_SIM" in line.upper() and "(NOT FOUND)" not in line.upper()
        for line in config_lines
    )
    configfs_available = any(line.strip() == "1" for line in sections["configfs"])
    gpiochips = [line.strip() for line in sections["dev"] if line.strip()]

    return {
        "kernel": next((line.strip() for line in sections["kernel"] if line.strip()), None),
        "module_available": modinfo_available,
        "modinfo": modinfo,
        "config": config_lines,
        "config_mentions_gpio_sim": config_mentions_gpio_sim,
        "configfs_available": configfs_available,
        "gpiochips": gpiochips,
        "ok": modinfo_available or config_mentions_gpio_sim,
    }
