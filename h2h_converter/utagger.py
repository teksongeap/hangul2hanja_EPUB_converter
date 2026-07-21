from __future__ import annotations

import contextlib
from ctypes import c_char_p, c_int, c_wchar_p, cdll
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Sequence

from . import config
from .ruby import has_hangul


CONFIG_MODE_RE = re.compile(r"(?m)^hangul_to_hanja\s+\d+\s*$")
CONFIG_LEVEL_RE = re.compile(r"(?m)^hanjaLevel\s+.*$")


def utagger3_library_name() -> str:
    """Platform-specific filename of the UTagger 3 native library.

    UTagger 3 packages ship both builds: UTaggerR64.dll (Windows x64) and
    UTagger.so (Linux x86_64). No macOS build exists.
    """
    return "UTaggerR64.dll" if os.name == "nt" else "UTagger.so"


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

        library_path = utagger_path / "bin" / utagger3_library_name()
        bin_path = utagger_path / "bin"
        if not library_path.exists():
            raise FileNotFoundError(f"UTagger library not found: {library_path}")

        # The native library takes the config path as a narrow C string: cp949
        # on Korean Windows, the filesystem encoding (UTF-8) elsewhere.
        config_path_bytes = (
            str(config_path).encode("cp949")
            if os.name == "nt"
            else os.fsencode(str(config_path))
        )

        previous_cwd = Path.cwd()
        try:
            os.chdir(bin_path)
            with _suppress_native_stdout():
                dll = cdll.LoadLibrary(str(library_path))
                dll.Global_init2.restype = c_wchar_p
                dll.Global_init2(c_char_p(config_path_bytes), c_int(0))
                dll.newUCMA2(c_int(self._thread))
                dll.cmaSetNewlineN(c_int(self._thread))
                dll.cma_tag_line_BSP.restype = c_wchar_p
            self._dll = dll
            UTaggerHanjaConverter._global_loaded = True
        finally:
            os.chdir(previous_cwd)

    def release(self) -> None:
        if self._dll is not None:
            with _suppress_native_stdout():
                self._dll.deleteUCMA(c_int(self._thread))
                self._dll.Global_release()
                # The Linux build logs shared-memory cleanup from a worker
                # thread; give it a moment to finish before restoring fds.
                time.sleep(0.15)
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


@contextlib.contextmanager
def _suppress_native_stdout():
    """Silence the UTagger library's dictionary-loading chatter.

    The UTagger 3 native library writes its loadIndex/loadDic progress (and
    its shared-memory release messages on Linux) directly to file descriptors
    1 and 2 during Global_init2/Global_release. That noise would bury the
    CLI's own output, so both fds are temporarily redirected to the null
    device while native calls run.
    """
    streams = [sys.stdout, sys.stderr]
    fds: list[int] = []
    for stream in streams:
        try:
            fds.append(stream.fileno())
        except (AttributeError, OSError, ValueError):
            continue
    fds = sorted(set(fds))
    if not fds:
        yield
        return

    for stream in streams:
        try:
            stream.flush()
        except (AttributeError, OSError, ValueError):
            continue

    saved = {fd: os.dup(fd) for fd in fds}
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        try:
            for fd in fds:
                os.dup2(devnull, fd)
        finally:
            os.close(devnull)
        yield
        # The native library buffers some of its log lines in the C runtime's
        # stdio buffers; flush them while the fds still point at the null
        # device, otherwise they surface later at process exit.
        _flush_c_streams()
    finally:
        for fd, saved_fd in saved.items():
            os.dup2(saved_fd, fd)
            os.close(saved_fd)


def _flush_c_streams() -> None:
    """fflush(NULL) on the C runtime(s) the native library may log through."""
    candidates = ["libc.so.6", "libc.dylib"] if os.name != "nt" else [
        "msvcrt",
        "ucrtbase",
        "api-ms-win-crt-stdio-l1-1-0",
    ]
    for name in candidates:
        try:
            cdll.LoadLibrary(name).fflush(None)
        except (OSError, AttributeError):
            continue


@dataclass(frozen=True)
class ResolvedInstall:
    """A located UTagger 3 install plus the source that supplied it."""

    path: Path
    source: str


def resolve_utagger3_path(explicit_path: Path | None) -> ResolvedInstall | None:
    """Find a UTagger 3 install, recording which source provided it.

    Precedence: --utagger3-path > UTAGGER3_PATH > h2h config file >
    pyutagger's saved path > .utagger/v3_* in the working directory.
    """
    if explicit_path is not None:
        return ResolvedInstall(Path(explicit_path).resolve(), "--utagger3-path")

    env_path = os.environ.get("UTAGGER3_PATH")
    if env_path:
        return ResolvedInstall(Path(env_path).resolve(), "UTAGGER3_PATH environment variable")

    config_path = config.get_utagger3_path()
    if config_path:
        return ResolvedInstall(config_path.resolve(), f"config file ({config.config_path()})")

    saved_path = _read_saved_pyutagger_path()
    if saved_path:
        return ResolvedInstall(saved_path.resolve(), "pyutagger saved path (~/pyutagger_path.json)")

    local_install = _find_local_workspace_install()
    if local_install:
        return ResolvedInstall(local_install.resolve(), "workspace .utagger folder")

    return None


def _resolve_utagger3_path(explicit_path: Path | None) -> Path:
    resolved = resolve_utagger3_path(explicit_path)
    if resolved is None:
        raise RuntimeError(
            "UTagger 3 is not configured. Run 'h2h-convert setup' to install it, "
            "or point at an existing install with --utagger3-path or UTAGGER3_PATH."
        )
    return resolved.path


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
        if (candidate / "bin" / utagger3_library_name()).exists():
            return candidate
    return None
