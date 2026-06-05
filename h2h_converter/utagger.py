from __future__ import annotations

from ctypes import c_char_p, c_int, c_wchar_p, cdll
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Sequence

from .ruby import has_hangul


CONFIG_MODE_RE = re.compile(r"(?m)^hangul_to_hanja\s+\d+\s*$")
CONFIG_LEVEL_RE = re.compile(r"(?m)^hanjaLevel\s+.*$")


@dataclass(frozen=True)
class UTaggerOptions:
    mode: int = 2
    hanja_levels: str | None = None
    base_config: Path | None = None
    utagger3_path: Path | None = None


class UTaggerHanjaConverter:
    """Small direct wrapper around UTagger 3's native DLL.

    UTagger's Hangul-to-Hanja controls live in Hlxcfg.txt, so this class
    creates a temporary config copy with the requested conversion mode.
    """

    _global_loaded = False

    def __init__(self, options: UTaggerOptions | None = None) -> None:
        self.options = options or UTaggerOptions()
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        self._dll = None
        self._thread = 0

    def __enter__(self) -> "UTaggerHanjaConverter":
        self.load()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # noqa: ANN001
        self.release()

    def load(self) -> None:
        if self._dll is not None:
            return
        if UTaggerHanjaConverter._global_loaded:
            raise RuntimeError("Only one UTagger 3 instance can be loaded per process.")

        utagger_path = _resolve_utagger3_path(self.options.utagger3_path)
        base_config = self.options.base_config or utagger_path / "Hlxcfg.txt"
        config_path = self._write_runtime_config(base_config)

        dll_path = utagger_path / "bin" / "UTaggerR64.dll"
        bin_path = utagger_path / "bin"
        if not dll_path.exists():
            raise FileNotFoundError(f"UTagger DLL not found: {dll_path}")

        previous_cwd = Path.cwd()
        try:
            os.chdir(bin_path)
            dll = cdll.LoadLibrary(str(dll_path))
            dll.Global_init2.restype = c_wchar_p
            dll.Global_init2(c_char_p(str(config_path).encode("cp949")), c_int(0))
            dll.newUCMA2(c_int(self._thread))
            dll.cmaSetNewlineN(c_int(self._thread))
            dll.cma_tag_line_BSP.restype = c_wchar_p
            self._dll = dll
            UTaggerHanjaConverter._global_loaded = True
        finally:
            os.chdir(previous_cwd)

    def release(self) -> None:
        if self._dll is not None:
            self._dll.deleteUCMA(c_int(self._thread))
            self._dll.Global_release()
            self._dll = None
            UTaggerHanjaConverter._global_loaded = False
        if self._temp_dir is not None:
            self._temp_dir.cleanup()
            self._temp_dir = None

    def convert(self, text: str) -> str:
        if not text or not has_hangul(text):
            return text
        if self._dll is None:
            raise RuntimeError("UTagger converter is not loaded.")

        raw = str(self._dll.cma_tag_line_BSP(c_int(self._thread), c_wchar_p(text), c_int(3)))
        return _extract_converted_sentence(raw, fallback=text)

    def convert_many(self, texts: Sequence[str]) -> list[str]:
        return [self.convert(text) for text in texts]

    def _write_runtime_config(self, base_config: Path) -> Path:
        if self.options.mode not in {1, 2}:
            raise ValueError("UTagger Hangul-to-Hanja mode must be 1 or 2.")
        if not base_config.exists():
            raise FileNotFoundError(f"UTagger config not found: {base_config}")

        config_text = base_config.read_text(encoding="utf-8")
        config_text = CONFIG_MODE_RE.sub(
            f"hangul_to_hanja {self.options.mode}", config_text, count=1
        )

        if self.options.hanja_levels:
            config_text = CONFIG_LEVEL_RE.sub(
                f"hanjaLevel {self.options.hanja_levels}", config_text, count=1
            )

        self._temp_dir = tempfile.TemporaryDirectory(prefix="h2h-utagger-")
        config_path = Path(self._temp_dir.name) / "Hlxcfg_h2h.txt"
        config_path.write_text(config_text, encoding="utf-8")
        return config_path


def _extract_converted_sentence(raw: str, fallback: str) -> str:
    lines = [line.strip() for line in raw.replace("\x00", "").splitlines() if line.strip()]
    if len(lines) >= 2:
        return lines[-1]
    return fallback


def _resolve_utagger3_path(explicit_path: Path | None) -> Path:
    if explicit_path is not None:
        return explicit_path.resolve()

    env_path = os.environ.get("UTAGGER3_PATH")
    if env_path:
        return Path(env_path).resolve()

    saved_path = _read_saved_pyutagger_path()
    if saved_path:
        return saved_path.resolve()

    local_install = _find_local_workspace_install()
    if local_install:
        return local_install.resolve()

    raise RuntimeError(
        "UTagger 3 is not configured. Pass --utagger3-path, set UTAGGER3_PATH, "
        "or install UTagger 3 with pyutagger's downloader first."
    )


def _read_saved_pyutagger_path() -> Path | None:
    config_path = Path.home() / "pyutagger_path.json"
    if not config_path.exists():
        return None
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw_path = data.get("utagger3")
    return Path(raw_path) if raw_path else None


def _find_local_workspace_install() -> Path | None:
    root = Path.cwd() / ".utagger"
    if not root.exists():
        return None
    candidates = sorted(root.glob("v3_*"), reverse=True)
    for candidate in candidates:
        if (candidate / "bin" / "UTaggerR64.dll").exists():
            return candidate
    return None
