from __future__ import annotations

import argparse
from pathlib import Path
import sys

from . import __version__
from .doctor import run_doctor
from .epub import convert_epub
from .installer import run_setup
from .utagger import UTaggerHanjaConverter, UTaggerOptions


SUBCOMMANDS = ("run", "setup", "doctor")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="h2h-convert",
        description="Convert a Korean EPUB into an EPUB with Hanja ruby annotations.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    run = subparsers.add_parser(
        "run",
        help="Convert an EPUB (this is the default when no command is given).",
        description="Convert a Korean EPUB into an EPUB with Hanja ruby annotations.",
    )
    run.add_argument("input_epub", type=Path)
    run.add_argument("output_epub", type=Path)
    run.add_argument(
        "--utagger3-path",
        type=Path,
        help="Path to a local UTagger 3 install. Overrides the saved and detected locations.",
    )
    run.add_argument(
        "--hanja-levels",
        help="Optional UTagger hanjaLevel list, for example: '0 1 2 3 4 5'.",
    )
    run.add_argument(
        "--no-css",
        action="store_true",
        help="Do not inject a small ruby display stylesheet into XHTML files.",
    )
    run.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace the output EPUB if it already exists.",
    )
    run.add_argument(
        "--strict",
        action="store_true",
        help="Stop on the first XHTML parse error instead of preserving that file unchanged.",
    )

    setup = subparsers.add_parser(
        "setup",
        help="Download UTagger 3 and remember where it lives.",
        description="Download UTagger 3 with pyutagger and save the install path.",
    )
    setup.add_argument(
        "--install-dir",
        type=Path,
        help="Where to install UTagger 3. Default: per-user data directory "
        "(%%LOCALAPPDATA%%\\h2h-converter\\utagger on Windows).",
    )

    doctor = subparsers.add_parser(
        "doctor",
        help="Verify the installation end to end.",
        description="Check Python, the UTagger 3 install, and a live conversion.",
    )
    doctor.add_argument(
        "--utagger3-path",
        type=Path,
        help="Check a specific UTagger 3 install instead of the configured one.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)

    # Backward compatibility: "h2h-convert in.epub out.epub" still converts.
    legacy = bool(argv) and not argv[0].startswith("-") and argv[0] not in SUBCOMMANDS
    if legacy:
        argv = ["run", *argv]

    args = build_parser().parse_args(argv)

    if args.command == "setup":
        return run_setup(args.install_dir)
    if args.command == "doctor":
        return run_doctor(args.utagger3_path)
    if args.command == "run":
        return _run_convert(args, legacy=legacy)

    build_parser().print_help()
    return 2


def _run_convert(args: argparse.Namespace, *, legacy: bool) -> int:
    if legacy:
        print("note: 'h2h-convert run ...' is the explicit form of this command.", file=sys.stderr)

    if not args.input_epub.exists():
        print(f"error: input EPUB not found: {args.input_epub}", file=sys.stderr)
        return 3

    options = UTaggerOptions(
        mode=2,
        hanja_levels=args.hanja_levels,
        utagger3_path=args.utagger3_path,
    )

    try:
        with UTaggerHanjaConverter(options) as converter:
            stats = convert_epub(
                args.input_epub,
                args.output_epub,
                converter,
                add_css=not args.no_css,
                best_effort=not args.strict,
                overwrite=args.overwrite,
            )
    except FileExistsError as exc:
        print(f"error: {exc} (use --overwrite to replace it)", file=sys.stderr)
        return 3
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"error: {args.input_epub} is not a readable EPUB: {exc}", file=sys.stderr)
        return 3
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4

    print(
        "Converted "
        f"{stats.documents} document(s), processed {stats.text_nodes} text segment(s), "
        f"and added {stats.ruby_nodes} ruby annotation(s)."
    )
    if stats.skipped_documents:
        print(
            f"Preserved {stats.skipped_documents} document(s) unchanged due to warnings.",
            file=sys.stderr,
        )
    for warning in stats.warnings[:5]:
        print(f"Warning: {warning}", file=sys.stderr)
    if len(stats.warnings) > 5:
        print(f"Warning: {len(stats.warnings) - 5} more warning(s) omitted.", file=sys.stderr)

    return 0


def _configure_stdio() -> None:
    """Write Korean text safely when output is piped on a non-UTF-8 console."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and not stream.isatty():
            stream.reconfigure(encoding="utf-8", errors="replace")
