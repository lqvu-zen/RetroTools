"""Persistence for the GUI's "device configs".

A device config is a snapshot of the Scan/M3U/Cheats tabs' folder paths and
options, keyed by device name and then by OS name -- e.g. a TrimUI Brick
running NextUI wants different folder conventions than the same handheld
running Spruce OS, so they're saved as separate leaves under one device
rather than one flat name. Switching between saved setups means picking two
names from lists instead of re-entering every folder each time.

Pure stdlib, no Qt import -- testable without PySide6 installed, unlike the
rest of the GUI.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Dict, Optional

#: Where configs live unless a test overrides it. A plain, human-editable
#: JSON file, consistent with this project's other on-disk artifacts (dry-run
#: plans, run logs) being plain text rather than an opaque store.
DEFAULT_CONFIG_PATH = Path.home() / ".retro-tools" / "configs.json"


@dataclass
class DeviceConfig:
    """One saved device's settings, covering all three GUI tabs at once."""

    roms_path: str = ""
    m3u_layout: str = "nextui"
    m3u_single_disc_folders: bool = False
    m3u_force: bool = False
    cheats_root: str = ""
    cheats_chtdb: str = ""
    cheats_force: bool = False


_FIELD_NAMES = {f.name for f in fields(DeviceConfig)}


def load_configs(path: Optional[Path] = None) -> Dict[str, Dict[str, DeviceConfig]]:
    """Load saved configs, tolerating a missing, corrupt, or foreign file.

    Returns ``{device_name: {os_name: DeviceConfig}}``. Unknown keys in a
    saved leaf are dropped and missing ones fall back to `DeviceConfig`'s
    defaults, so a config saved by an older or newer version of this tool
    still loads instead of breaking the whole file. A device or OS entry
    that isn't shaped like a nested mapping is skipped rather than raising,
    and a device left with no valid OS entries is dropped entirely.
    """
    path = path or DEFAULT_CONFIG_PATH
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}

    configs: Dict[str, Dict[str, DeviceConfig]] = {}
    for device, os_map in raw.items():
        if not isinstance(os_map, dict):
            continue
        device_configs = {}
        for os_name, data in os_map.items():
            if not isinstance(data, dict):
                continue
            device_configs[os_name] = DeviceConfig(
                **{k: v for k, v in data.items() if k in _FIELD_NAMES}
            )
        if device_configs:
            configs[device] = device_configs
    return configs


def save_configs(configs: Dict[str, Dict[str, DeviceConfig]], path: Optional[Path] = None) -> None:
    """Write *configs* to disk as plain, human-editable JSON."""
    path = path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        device: {os_name: asdict(config) for os_name, config in os_map.items()}
        for device, os_map in configs.items()
    }
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
