"""Per-user configuration for h2h-converter.

The converter itself stays dependency-free; this module only uses the standard
library. Configuration lives in a small JSON file so that ``h2h-convert setup``
can remember where UTagger 3 was installed and ``doctor`` can explain which
source supplied the path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


APP_NAME = "h2h-converter"


def config_dir() -> Path:
    """Directory holding config.json (%APPDATA% on Windows, ~/.config elsewhere)."""
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def data_dir() -> Path:
    """Directory for downloaded data such as UTagger (%LOCALAPPDATA% on Windows)."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.json"


def default_utagger_install_dir() -> Path:
    """Default base directory for ``h2h-convert setup`` to install UTagger 3 into."""
    return data_dir() / "utagger"


def load_config() -> dict:
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(config: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def get_utagger3_path() -> Path | None:
    raw = load_config().get("utagger3_path")
    return Path(raw) if raw else None


def save_utagger3_path(path: Path) -> Path:
    """Record the UTagger 3 install location; returns the config file written."""
    config = load_config()
    config["utagger3_path"] = str(path)
    return save_config(config)
