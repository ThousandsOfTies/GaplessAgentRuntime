"""Hardware definition CSV helpers for ``gar hw``."""

from __future__ import annotations

import csv
from pathlib import Path

from scripts.gar_lib._config import PROJECT_ROOT

HW_TEMPLATE_FILES: dict[str, list[str]] = {
    "components.csv": [
        "component_id",
        "name",
        "kind",
        "part_number",
        "description",
    ],
    "gpio.csv": [
        "name",
        "chip",
        "line",
        "direction",
        "role",
        "active",
        "initial",
        "pull",
        "sim_control",
        "description",
    ],
    "i2c.csv": [
        "name",
        "bus",
        "dev",
        "address",
        "driver",
        "sim",
        "description",
    ],
    "spi.csv": [
        "name",
        "bus",
        "chip_select",
        "dev",
        "mode",
        "max_speed_hz",
        "driver",
        "sim",
        "description",
    ],
    "connections.csv": [
        "source",
        "source_pin",
        "target",
        "target_pin",
        "signal",
        "description",
    ],
}

HW_DIR = PROJECT_ROOT / "hardware"


def _resolve_hw_dir(output_dir: str | None) -> Path:
    if output_dir:
        path = Path(output_dir).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path
    return HW_DIR


def _read_hw_csv(hw_dir: Path, name: str) -> list[dict[str, str]]:
    path = hw_dir / name
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [
            {str(key): (value or "").strip() for key, value in row.items() if key is not None}
            for row in reader
            if any((value or "").strip() for value in row.values())
        ]


def load_hw_definition(*, hw_dir: str | None = None) -> dict[str, list[dict[str, str]]]:
    """Load hardware assignment CSV files as plain row dictionaries."""

    root = _resolve_hw_dir(hw_dir)
    return {
        "components": _read_hw_csv(root, "components.csv"),
        "gpio": _read_hw_csv(root, "gpio.csv"),
        "i2c": _read_hw_csv(root, "i2c.csv"),
        "spi": _read_hw_csv(root, "spi.csv"),
        "connections": _read_hw_csv(root, "connections.csv"),
    }


def write_hw_template(*, output_dir: str | None = None, force: bool = False) -> int:
    """Create empty hardware definition CSV files."""

    hw_dir = _resolve_hw_dir(output_dir)
    existing = [name for name in HW_TEMPLATE_FILES if (hw_dir / name).exists()]
    if existing and not force:
        print(
            "gar hw init: already exists: "
            + ", ".join(str(hw_dir / name) for name in existing)
        )
        print("gar hw init: use --force to overwrite template files")
        return 1

    hw_dir.mkdir(parents=True, exist_ok=True)
    for name, headers in HW_TEMPLATE_FILES.items():
        path = hw_dir / name
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(headers)
        print(f"created {path}")

    return 0


def run_hw_command(command: str, *, output_dir: str | None = None, force: bool = False) -> int:
    if command == "init":
        return write_hw_template(output_dir=output_dir, force=force)

    print(f"gar hw: unknown command: {command}")
    return 1
