"""Implementation of ``h2h-convert doctor``: end-to-end install verification."""

from __future__ import annotations

from pathlib import Path
import struct
import sys

from .utagger import UTaggerHanjaConverter, UTaggerOptions, resolve_utagger3_path


TEST_SENTENCE = "대한민국의 역사는 오래되었다."
EXPECTED_MARKERS = ("대한민국(大韓民國)", "역사(歷史)")


def run_doctor(utagger3_path: Path | None = None) -> int:
    failures = 0

    def ok(message: str) -> None:
        print(f"  [ok] {message}")

    def fail(message: str, fix: str | None = None) -> None:
        nonlocal failures
        failures += 1
        print(f"  [FAIL] {message}")
        if fix:
            print(f"         fix: {fix}")

    print("h2h-convert doctor: checking your installation")

    version = sys.version.split()[0]
    if sys.version_info >= (3, 10):
        ok(f"Python {version} (3.10 or newer required)")
    else:
        fail(
            f"Python {version} is too old; 3.10 or newer is required.",
            "Install a current 64-bit CPython from python.org.",
        )

    if struct.calcsize("P") == 8:
        ok("64-bit interpreter (required by the UTagger DLL)")
    else:
        fail(
            "32-bit Python cannot load UTagger's 64-bit DLL.",
            "Install 64-bit CPython and recreate your virtual environment.",
        )

    resolved = resolve_utagger3_path(utagger3_path)
    if resolved is None:
        fail(
            "UTagger 3 install location could not be resolved.",
            "Run 'h2h-convert setup' or pass --utagger3-path.",
        )
        print(f"\ndoctor: {failures} check(s) failed.")
        return 4
    ok(f"UTagger 3 path: {resolved.path} (from {resolved.source})")

    expected_files = [resolved.path / "bin" / "UTaggerR64.dll", resolved.path / "Hlxcfg.txt"]
    missing = [path for path in expected_files if not path.exists()]
    if missing:
        for path in missing:
            fail(f"Missing file: {path}", "Re-run 'h2h-convert setup' to reinstall UTagger 3.")
        print(f"\ndoctor: {failures} check(s) failed.")
        return 4
    ok("UTagger DLL and configuration files are present")

    try:
        with UTaggerHanjaConverter(UTaggerOptions(utagger3_path=resolved.path)) as converter:
            converted = converter.convert(TEST_SENTENCE)
    except Exception as exc:  # noqa: BLE001 - doctor reports any initialization failure
        fail(
            f"UTagger failed to initialize or convert text ({exc}).",
            "Re-run 'h2h-convert setup'; also check that no other h2h process is running.",
        )
        print(f"\ndoctor: {failures} check(s) failed.")
        return 4

    if all(marker in converted for marker in EXPECTED_MARKERS):
        ok(f"live conversion: {TEST_SENTENCE} -> {converted}")
    else:
        fail(
            f"UTagger converted text but the output looks wrong: {converted}",
            "The dictionaries may be damaged; re-run 'h2h-convert setup'.",
        )

    print()
    if failures:
        print(f"doctor: {failures} check(s) failed.")
        return 4
    print("doctor: all checks passed. You are ready to convert EPUBs.")
    return 0
