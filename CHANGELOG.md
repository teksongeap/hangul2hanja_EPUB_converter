# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] - 2026-07-21

A setup-and-usage overhaul driven by the UX improvement plan in
`docs/ux-improvement-plan.md`, plus native Linux support.

### Added

- `h2h-convert setup`: downloads UTagger 3 into a per-user data directory
  (reuses an existing install when present), checks 64-bit Python and disk
  space, and saves the location to a config file
  (`%APPDATA%\h2h-converter\config.json`, `~/.config/h2h-converter/config.json`).
- `h2h-convert doctor`: end-to-end verification — Python version and
  architecture, UTagger path resolution (naming the source), library presence,
  and a live conversion. Exits 0 only when everything passes.
- `h2h-convert run` ergonomics:
  - default output name `<stem>.hanja-ruby.epub` when no output is given
  - batch mode: multiple files, folders, or glob patterns with `--output-dir`,
    one shared UTagger instance, existing outputs skipped for resumable batches
  - `--preview N`: print before/after pairs for the first N text segments
    without writing an output file
  - per-document progress on stderr (redrawn line on a terminal, plain lines
    when piped)
  - `--verbose` / `--quiet` and `--report FILE` for the full warning list
- Documented exit codes: `0` ok, `2` usage, `3` input/output, `4` UTagger,
  `5` partial success.
- `--version`.
- Native Linux (x86_64) support: the converter loads `UTagger.so` on Linux and
  `UTaggerR64.dll` on Windows. Verified byte-identical conversion output.
- `.python-version` (3.12).

### Changed

- UTagger path resolution order is now: `--utagger3-path` > `UTAGGER3_PATH` >
  h2h config file > pyutagger's saved path > `.utagger/v3_*` in the working
  directory — and it is documented in the README.
- Routine failures (missing input, existing output, unconfigured UTagger,
  unreadable EPUB) print one-line actionable errors with exit codes instead of
  tracebacks.
- The UTagger native library's dictionary-loading chatter on stdout/stderr is
  suppressed during initialization and shutdown.
- `convert-samples.ps1` is now a thin wrapper around the CLI's native batch
  mode — the embedded Python here-string is gone.
- README rewritten fresh-machine-first: requirements (Windows/Linux), venv
  setup, `setup`/`doctor`, preview/batch examples, troubleshooting.

### Removed

- `requirements.txt` — `pyproject.toml` is the single dependency source
  (`pip install -e ".[setup]"` for the UTagger downloader extra).
- All references to the developer's local WinPython path.

### Deprecated

- `h2h-convert input.epub output.epub` without the `run` subcommand still
  works but prints a deprecation note.

## [0.1.0] - 2026-06-05

Initial working pipeline: EPUB unpacking, spine XHTML parsing with entity
repair, paragraph-scope Hangul-to-Hanja conversion via a local UTagger 3
native library, ruby markup injection with a small stylesheet, and correct
EPUB repacking (uncompressed `mimetype` first).
