"""Implementation of ``h2h-convert setup``: guided UTagger 3 installation."""

from __future__ import annotations

from pathlib import Path
import shutil
import struct

from . import config
from .utagger import utagger3_library_name


UTAGGER_VERSION_KEY = "utagger3"
MIN_FREE_BYTES = 300 * 1024 * 1024  # UTagger 3 needs roughly 200 MB


def _load_downloader():
    """Import pyutagger's downloader lazily so the CLI never requires it."""
    from pyutagger import downloader

    return downloader


def find_utagger3_install(base_dir: Path) -> Path | None:
    """Locate a usable UTagger 3 install (one with the library) under a base directory."""
    if (base_dir / "bin" / utagger3_library_name()).exists():
        return base_dir
    candidates = sorted(base_dir.glob("v3_*"), reverse=True)
    for candidate in candidates:
        if (candidate / "bin" / utagger3_library_name()).exists():
            return candidate
    return None


def run_setup(install_dir: Path | None) -> int:
    print("h2h-convert setup: install UTagger 3")

    if struct.calcsize("P") != 8:
        print("[FAIL] A 64-bit Python interpreter is required: UTagger ships as a 64-bit native library.")
        print("       fix: install 64-bit CPython and recreate your virtual environment.")
        return 2

    base_dir = (install_dir or config.default_utagger_install_dir()).resolve()
    print(f"  install location: {base_dir}")

    existing = find_utagger3_install(base_dir) if base_dir.exists() else None
    if existing is not None:
        print(f"  [ok] found an existing UTagger 3 install, reusing it: {existing}")
        utagger_path = existing
    else:
        try:
            downloader = _load_downloader()
        except ImportError:
            print("[FAIL] pyutagger is not installed, so UTagger cannot be downloaded.")
            print('       fix: pip install -e ".[setup]"')
            return 2

        base_dir.mkdir(parents=True, exist_ok=True)
        free_bytes = shutil.disk_usage(base_dir).free
        print(f"  free disk space: {free_bytes / (1024 ** 2):.0f} MB (UTagger needs about 200 MB)")
        if free_bytes < MIN_FREE_BYTES:
            print("[FAIL] Not enough free disk space for the UTagger download.")
            return 4

        print("  downloading UTagger 3 binaries and dictionaries ...")
        if not downloader.install_utagger(UTAGGER_VERSION_KEY, str(base_dir)):
            print("[FAIL] The UTagger download failed (see the downloader output above).")
            print("       fix: check your network connection and run 'h2h-convert setup' again.")
            return 4

        utagger_path = find_utagger3_install(base_dir)
        if utagger_path is None:
            print(f"[FAIL] The download finished but no usable install was found under {base_dir}.")
            return 4

    written = config.save_utagger3_path(utagger_path)
    print(f"  [ok] UTagger 3 ready at: {utagger_path}")
    print(f"  [ok] install path saved to: {written}")
    print()
    print("Next step: h2h-convert doctor")
    return 0
