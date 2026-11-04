"""ESP32 firmware artifact layout used by the physical target deployer."""

from __future__ import annotations

import json
from pathlib import Path

FLASH_LAYOUT = (
    ("0x1000", "bootloader.bin"),
    ("0x8000", "partitions.bin"),
    ("0xE000", "boot_app0.bin"),
    ("0x10000", "firmware.bin"),
)


def flash_profile(artifact_dir: Path):
    """Opt-in chip profile; legacy bundles retain the original ESP32 layout."""
    descriptor = artifact_dir / "flash.json"
    if not descriptor.exists():
        return "esp32", FLASH_LAYOUT
    data = json.loads(descriptor.read_text(encoding="utf-8"))
    chip = data.get("chip")
    if data.get("schema_version") != 1 or chip not in {"esp32", "esp32s3"}:
        raise ValueError("Unsupported ESP32 flash profile")
    layout = (("0x0" if chip == "esp32s3" else "0x1000", "bootloader.bin"), *FLASH_LAYOUT[1:])
    chip_id = 9 if chip == "esp32s3" else 0
    for _offset, name in layout:
        path = artifact_dir / name
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Missing or empty flash image: {name}")
        if name in {"bootloader.bin", "firmware.bin"}:
            header = path.read_bytes()[:24]
            if len(header) != 24 or header[0] != 0xE9 or int.from_bytes(header[12:14], "little") != chip_id:
                raise ValueError(f"{name}: image chip does not match {chip}")
    for (offset, name), (next_offset, _) in zip(layout, layout[1:], strict=False):
        if int(offset, 16) + (artifact_dir / name).stat().st_size > int(next_offset, 16):
            raise ValueError(f"Overlapping flash images: {name}")
    return chip, layout


def resolve_esp32_artifact_dir(artifact_dir: str | None) -> Path | None:
    """Resolve the artifact explicitly supplied by the product build pipeline."""

    if artifact_dir is None:
        return None
    return Path(artifact_dir).expanduser().resolve()
