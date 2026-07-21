from __future__ import annotations

import argparse
import glob
from pathlib import Path
import sys

from . import __version__
from .doctor import run_doctor
from .epub import ConversionStats, collect_epub_texts, convert_epub
from .installer import run_setup
from .utagger import UTaggerHanjaConverter, UTaggerOptions


SUBCOMMANDS = ("run", "setup", "doctor")
DEFAULT_OUTPUT_SUFFIX = ".hanja-ruby.epub"
PREVIEW_SEGMENT_CHAR_LIMIT = 300


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="h2h-convert",
        description="Convert a Korean EPUB into an EPUB with Hanja ruby annotations.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    run = subparsers.add_parser(
        "run",
        help="Convert EPUB(s) (this is the default when no command is given).",
        description="Convert Korean EPUBs into EPUBs with Hanja ruby annotations.",
        epilog=(
            "examples:\n"
            "  h2h-convert run book.epub                    # writes book.hanja-ruby.epub\n"
            "  h2h-convert run book.epub out.epub           # explicit output file\n"
            "  h2h-convert run book1.epub book2.epub -d out # batch into a folder\n"
            '  h2h-convert run "D:\\Books\\*.epub" -d out     # glob batch\n'
            "  h2h-convert run D:\\Books -d out             # every EPUB in a folder\n"
            "  h2h-convert run book.epub --preview          # sample the annotations first"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        metavar="input",
        help="Input EPUB(s): files, a folder of EPUBs, or a glob pattern. "
        "With exactly two file arguments and no --output-dir, the second is the output file.",
    )
    run.add_argument(
        "-d",
        "--output-dir",
        type=Path,
        help="Batch mode: write <name>.hanja-ruby.epub for every input into this folder.",
    )
    run.add_argument(
        "--preview",
        nargs="?",
        const=10,
        default=None,
        type=int,
        metavar="N",
        help="Show before/after pairs for the first N text segments (default 10) "
        "without writing an output file.",
    )
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
        help="Replace existing output EPUBs (batch mode skips existing outputs without it).",
    )
    run.add_argument(
        "--strict",
        action="store_true",
        help="Stop on the first XHTML parse error instead of preserving that file unchanged.",
    )
    run.add_argument(
        "--report",
        type=Path,
        metavar="FILE",
        help="Write the full warning list to FILE (warnings are truncated on screen by default).",
    )
    verbosity = run.add_mutually_exclusive_group()
    verbosity.add_argument(
        "--verbose",
        action="store_true",
        help="Print every warning instead of truncating the list.",
    )
    verbosity.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress and summaries; only errors are printed.",
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
        "(%%LOCALAPPDATA%%\\h2h-converter\\utagger on Windows, "
        "~/.local/share/h2h-converter/utagger on Linux).",
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

    positionals = list(args.inputs)
    explicit_output: Path | None = None
    raw_inputs: list[Path]

    if args.preview is not None:
        if args.preview < 1:
            return _usage_error("--preview expects a positive number of segments.")
        if args.output_dir is not None:
            return _usage_error("--preview cannot be combined with --output-dir.")
        if len(positionals) > 1:
            return _usage_error("--preview writes nothing; pass only the input EPUB.")
        raw_inputs = positionals
    elif args.output_dir is not None:
        raw_inputs = positionals
    elif len(positionals) == 1:
        raw_inputs = positionals
    elif len(positionals) == 2:
        raw_inputs = positionals[:1]
        explicit_output = positionals[1]
    else:
        return _usage_error(
            "converting several EPUBs needs batch mode: add --output-dir DIR "
            "(run 'h2h-convert run --help' for examples)."
        )

    try:
        inputs = _expand_inputs(raw_inputs)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    reporter = _ProgressReporter(quiet=args.quiet)

    if args.preview is not None:
        return _run_preview(inputs[0], args.preview, args)

    if args.output_dir is not None:
        outputs = [args.output_dir / f"{epub.stem}{DEFAULT_OUTPUT_SUFFIX}" for epub in inputs]
        duplicates = sorted({out.name for out in outputs if outputs.count(out) > 1})
        if duplicates:
            return _usage_error(
                "several inputs would produce the same output name(s): "
                + ", ".join(duplicates)
                + ". Rename the inputs or convert them separately."
            )
        return _run_batch(inputs, args, reporter)

    output = explicit_output or inputs[0].with_name(f"{inputs[0].stem}{DEFAULT_OUTPUT_SUFFIX}")
    return _run_single(inputs[0], output, args, reporter)


def _run_single(
    input_epub: Path,
    output_epub: Path,
    args: argparse.Namespace,
    reporter: "_ProgressReporter",
) -> int:
    try:
        converter = _load_converter(args)
        converter.load()
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4

    with converter:
        try:
            stats = convert_epub(
                input_epub,
                output_epub,
                converter,
                add_css=not args.no_css,
                best_effort=not args.strict,
                overwrite=args.overwrite,
                progress=reporter,
            )
        except FileExistsError as exc:
            print(f"error: {exc} (use --overwrite to replace it)", file=sys.stderr)
            return 3
        except (FileNotFoundError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 3
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 4

    if not args.quiet:
        print(_stats_line(stats))
    _emit_warnings(input_epub.name, stats, args)
    _write_report(args.report, [(input_epub.name, stats.warnings)])
    return 5 if stats.skipped_documents else 0


def _run_batch(
    inputs: list[Path],
    args: argparse.Namespace,
    reporter: "_ProgressReporter",
) -> int:
    try:
        converter = _load_converter(args)
        converter.load()
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4

    converted: list[Path] = []
    skipped: list[Path] = []
    failed: list[tuple[Path, str]] = []
    preserved_docs = 0
    report_sections: list[tuple[str, list[str]]] = []

    with converter:
        for index, epub in enumerate(inputs, start=1):
            output = args.output_dir / f"{epub.stem}{DEFAULT_OUTPUT_SUFFIX}"
            if not args.quiet:
                print(f"[{index}/{len(inputs)}] {epub.name} -> {output.name}", file=sys.stderr)
            try:
                stats = convert_epub(
                    epub,
                    output,
                    converter,
                    add_css=not args.no_css,
                    best_effort=not args.strict,
                    overwrite=args.overwrite,
                    progress=reporter,
                )
            except FileExistsError:
                skipped.append(epub)
                print(f"  skipped: {output} already exists (use --overwrite)", file=sys.stderr)
                continue
            except (FileNotFoundError, ValueError, RuntimeError) as exc:
                failed.append((epub, str(exc)))
                print(f"  error: {exc}", file=sys.stderr)
                continue

            converted.append(epub)
            preserved_docs += stats.skipped_documents
            report_sections.append((epub.name, stats.warnings))
            if not args.quiet:
                print(f"  {_stats_line(stats)}", file=sys.stderr)
            _emit_warnings(epub.name, stats, args)

    _write_report(args.report, report_sections)

    parts = [f"{len(converted)} converted"]
    if skipped:
        parts.append(f"{len(skipped)} skipped (output exists)")
    if failed:
        parts.append(f"{len(failed)} failed")
    print(f"Batch complete: {', '.join(parts)} of {len(inputs)} file(s).")
    for epub, message in failed:
        print(f"  failed: {epub.name}: {message}", file=sys.stderr)

    if not converted and not skipped and failed:
        return 3
    if failed or skipped or preserved_docs:
        return 5
    return 0


def _run_preview(input_epub: Path, count: int, args: argparse.Namespace) -> int:
    try:
        texts = collect_epub_texts(input_epub, count)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    if not texts:
        print(f"No Korean text segments found in the first spine documents of {input_epub.name}.")
        return 0

    try:
        converter = _load_converter(args)
        converter.load()
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4

    with converter:
        pairs = [(doc, text, converter.convert(text)) for doc, text in texts]

    print(f"preview: first {len(pairs)} Korean text segment(s) of {input_epub.name}")
    print("(this is a sample only - no output file was written)")
    for index, (doc, original, converted) in enumerate(pairs, start=1):
        print(f"\n[{index}] {doc}")
        print(f"  before: {_truncate(original)}")
        print(f"  after:  {_truncate(converted)}")
    return 0


def _load_converter(args: argparse.Namespace) -> UTaggerHanjaConverter:
    options = UTaggerOptions(
        mode=2,
        hanja_levels=args.hanja_levels,
        utagger3_path=args.utagger3_path,
    )
    return UTaggerHanjaConverter(options)


def _expand_inputs(raw_inputs: list[Path]) -> list[Path]:
    """Resolve files, folders, and glob patterns into a de-duplicated EPUB list."""
    expanded: list[Path] = []
    for raw in raw_inputs:
        text = str(raw)
        if any(char in text for char in "*?["):
            matches = [Path(match) for match in sorted(glob.glob(text))]
            epubs = [match for match in matches if match.suffix.lower() == ".epub"]
            if not epubs:
                raise ValueError(f"no EPUB files match pattern: {text}")
            expanded.extend(epubs)
        elif raw.is_dir():
            # Skip our own default-suffixed outputs so re-running a batch in
            # place does not convert already-converted books again.
            epubs = sorted(
                path for path in raw.glob("*.epub") if not path.name.endswith(DEFAULT_OUTPUT_SUFFIX)
            )
            if not epubs:
                raise ValueError(f"no .epub files found in folder: {raw}")
            expanded.extend(epubs)
        else:
            expanded.append(raw)

    missing = [path for path in expanded if not path.exists()]
    if missing:
        raise ValueError("input EPUB not found: " + ", ".join(str(path) for path in missing))

    unique: list[Path] = []
    seen: set[str] = set()
    for path in expanded:
        key = str(path.resolve()).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _emit_warnings(name: str, stats: ConversionStats, args: argparse.Namespace) -> None:
    if args.quiet or not stats.warnings:
        return
    if stats.skipped_documents:
        print(
            f"  preserved {stats.skipped_documents} document(s) unchanged due to warnings.",
            file=sys.stderr,
        )
    limit = len(stats.warnings) if args.verbose else 5
    for warning in stats.warnings[:limit]:
        print(f"  warning: {warning}", file=sys.stderr)
    hidden = len(stats.warnings) - limit
    if hidden > 0:
        hint = f" (use --verbose or --report FILE to see all {len(stats.warnings)})"
        print(f"  warning: {hidden} more warning(s) omitted.{hint}", file=sys.stderr)


def _write_report(report_path: Path | None, sections: list[tuple[str, list[str]]]) -> None:
    if report_path is None:
        return
    lines = ["h2h-convert warning report", ""]
    total = 0
    for name, warnings in sections:
        for warning in warnings:
            lines.append(f"{name}: {warning}")
            total += 1
    if total == 0:
        lines.append("no warnings")
    else:
        lines.append("")
        lines.append(f"{total} warning(s) total")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Full warning report written to {report_path}", file=sys.stderr)


def _stats_line(stats: ConversionStats) -> str:
    return (
        f"{stats.documents} document(s), {stats.text_nodes} text segment(s), "
        f"{stats.ruby_nodes} ruby annotation(s)"
    )


def _truncate(text: str) -> str:
    flattened = " ".join(text.split())
    if len(flattened) <= PREVIEW_SEGMENT_CHAR_LIMIT:
        return flattened
    return flattened[:PREVIEW_SEGMENT_CHAR_LIMIT] + " ..."


def _usage_error(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


class _ProgressReporter:
    """TTY-aware per-document progress on stderr.

    On a terminal the current line is redrawn in place; when piped, plain
    lines are written so logs keep the full sequence.
    """

    def __init__(self, quiet: bool) -> None:
        self._enabled = not quiet
        self._tty = sys.stderr.isatty()
        self._width = 0

    def __call__(self, current: int, total: int, name: str) -> None:
        if not self._enabled:
            return
        line = f"  doc {current}/{total}: {name}"
        if not self._tty:
            print(line, file=sys.stderr)
            return

        self._width = max(self._width, len(line))
        print("\r" + line.ljust(self._width), end="", file=sys.stderr, flush=True)
        if current == total:
            print(file=sys.stderr, flush=True)
            self._width = 0


def _configure_stdio() -> None:
    """Write Korean text safely when output is piped on a non-UTF-8 console."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and not stream.isatty():
            stream.reconfigure(encoding="utf-8", errors="replace")
