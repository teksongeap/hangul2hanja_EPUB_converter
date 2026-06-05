from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .epub import convert_epub
from .utagger import UTaggerHanjaConverter, UTaggerOptions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="h2h-convert",
        description="Convert a Korean EPUB into an EPUB with Hanja ruby annotations.",
    )
    parser.add_argument("input_epub", type=Path)
    parser.add_argument("output_epub", type=Path)
    parser.add_argument(
        "--utagger3-path",
        type=Path,
        help="Path to a local UTagger 3 install. If omitted, pyutagger's saved path is used.",
    )
    parser.add_argument(
        "--hanja-levels",
        help="Optional UTagger hanjaLevel list, for example: '0 1 2 3 4 5'.",
    )
    parser.add_argument(
        "--no-css",
        action="store_true",
        help="Do not inject a small ruby display stylesheet into XHTML files.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace the output EPUB if it already exists.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Stop on the first XHTML parse error instead of preserving that file unchanged.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    options = UTaggerOptions(
        mode=2,
        hanja_levels=args.hanja_levels,
        utagger3_path=args.utagger3_path,
    )

    with UTaggerHanjaConverter(options) as converter:
        stats = convert_epub(
            args.input_epub,
            args.output_epub,
            converter,
            add_css=not args.no_css,
            best_effort=not args.strict,
            overwrite=args.overwrite,
        )

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
