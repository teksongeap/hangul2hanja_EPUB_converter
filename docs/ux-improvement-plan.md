# H2H Converter — Setup & Usage UX Improvement Plan

Date: 2026-07-21
Scope: make installing, configuring, and running the converter feel like a normal,
well-behaved tool instead of a machine-specific experiment. The current reliance on a
hardcoded WinPython path is the most visible symptom; this plan fixes the root causes.

---

## 1. Current state audit

### What the tool is
A zero-runtime-dependency Python package (`h2h_converter`) that:
- unpacks an EPUB in memory,
- finds spine XHTML documents via `container.xml` → OPF,
- sends Korean paragraph-scope text to a locally installed UTagger 3 native DLL
  (`UTaggerR64.dll`, loaded via `ctypes`),
- rewrites `한글(漢字)` output as `<ruby>` markup,
- injects a small ruby stylesheet, repacks the EPUB correctly
  (uncompressed `mimetype` first).

The conversion core is solid and tested (paragraph-scope alignment, entity repair,
best-effort vs `--strict` handling). **The pain is everything around the core.**

### Setup flow today
1. README tells the reader to use `C:\tmp\WinPython\WPy64-3.13.12.0\python\python.exe`
   — a path that only exists on the original developer's machine.
2. `pip install -r requirements.txt` installs `pyutagger` (a *setup-time* helper).
3. A one-liner `python -c "import pyutagger.downloader ..."` downloads UTagger 3 to
   `C:\utagger` (or wherever the user thinks to put it).
4. At runtime the converter hunts for UTagger through a 4-layer implicit chain:
   `--utagger3-path` → `UTAGGER3_PATH` env var → `~/pyutagger_path.json` →
   `.utagger/v3_*` under the current working directory.

### Usage flow today
- Single file per invocation: `python -m h2h_converter in.epub out.epub --overwrite`.
- Batch conversion only via `convert-samples.ps1`, which:
  - hardcodes the same WinPython path as a default parameter (falls back to `python`),
  - shells out to `python -c` with an **embedded Python program in a here-string**,
  - is tied to the repo's `sample_epubs/` / `data/` folders, not the user's books.
- No progress output during a conversion; a 500-page novel looks frozen.
- No way to preview what the annotations will look like before converting a whole book.
- Common failures (missing input, output exists, UTagger not found) surface as raw
  Python tracebacks.
- Warnings are truncated to 5 with no way to see the rest.
- `pyproject.toml` is correct (`h2h-convert` console script, zero deps) but the README
  never tells anyone to actually `pip install` the package.

---

## 2. Pain points, ranked

| # | Pain | Who it hits | Severity |
|---|------|-------------|----------|
| P1 | WinPython path hardcoded in README + `convert-samples.ps1`; no venv guidance | Every new user, first 5 minutes | Blocker for anyone but the original dev |
| P2 | UTagger provisioning is a manual one-liner to a magic folder; 4-layer implicit path resolution; no way to ask "is my install working?" | Every new user | High |
| P3 | Batch mode only exists as a PowerShell script with an embedded Python here-string and a machine-local interpreter default | Anyone converting >1 book | High |
| P4 | No progress reporting, no preview/dry-run, truncated warnings | Every user, every conversion | Medium |
| P5 | Raw tracebacks for routine errors (file exists, UTagger missing); no exit-code contract | Every user | Medium |
| P6 | README documents this machine, not a fresh machine; two competing dependency sources (`requirements.txt` vs `pyproject.toml` extra) | New users, contributors | Medium |
| P7 | No packaged distribution; the actual audience (Korean readers, not necessarily Python users) must install Python at all | Non-technical end users | Strategic / later |

---

## 3. Improvement plan

### Phase 1 — Kill the WinPython dependency (packaging hygiene)

> **Status: landed 2026-07-21.** README now leads with a venv + `pip install -e ".[setup]"`
> flow, `requirements.txt` is deleted, `convert-samples.ps1` discovers the interpreter via
> `-PythonPath` → `H2H_PYTHON` → `.venv` → PATH (no absolute machine paths), a
> `.python-version` (3.12) was added, and `UTaggerPath` is only passed when explicit or
> repo-local. All 18 tests pass.

**Goal: `git clone` → working converter in ≤ 4 commands, using stock Python.**

1. **Replace all WinPython references with a standard venv flow:**
   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -e ".[setup]"
   h2h-convert doctor
   ```
   Any Python ≥ 3.10 x64 works (the DLL is x64-only — document this explicitly;
   32-bit Python is the one real incompatibility).
2. **Single source of dependencies:** delete `requirements.txt` (or reduce it to
   `-e .[setup]`). `pyutagger` stays an optional `setup` extra — it is only needed to
   *download* UTagger, never at conversion time. Runtime deps stay empty; that is a
   feature worth preserving and stating in the README.
3. **`convert-samples.ps1` interpreter discovery**, in order:
   `$env:H2H_PYTHON` → `.venv\Scripts\python.exe` → `python` on PATH.
   Never default to an absolute `C:\...` path. Fail with a clear message naming the
   search order.
4. Add a `.python-version` (3.12) and a short "supported environments" note:
   Windows 10/11 x64, CPython 3.10–3.13.

### Phase 2 — First-run experience: `setup` and `doctor` subcommands

> **Status: landed 2026-07-21.** The CLI is now subcommand-based (`run` / `setup` /
> `doctor`, stdlib argparse, zero dependencies added) with the bare positional form kept
> as a deprecated alias. `setup` wraps pyutagger with a per-user default install dir,
> existing-install reuse, disk-space and 64-bit pre-checks, and writes
> `%APPDATA%\h2h-converter\config.json`. `doctor` verifies Python version/architecture,
> reports *which* source resolved the UTagger path (new `resolve_utagger3_path` with
> config-file precedence documented), loads the DLL, and runs the known-good live
> conversion — verified against the real install (exit 0). Friendly one-line errors with
> exit codes 2/3/4 replaced tracebacks for routine failures, the UTagger DLL's stdout
> chatter is now suppressed at the fd level, and 18 new tests cover config, resolution,
> CLI parsing, doctor, and installer (36 total passing).

**Goal: the tool tells the user what is wrong and how to fix it, in its own words.**

Turn the flat CLI into subcommands (stdlib `argparse` subparsers — keeps the
zero-dependency rule):

```
h2h-convert setup [--install-dir DIR]     # guided UTagger 3 download via pyutagger
h2h-convert doctor [--utagger3-path DIR]  # verify the whole chain end-to-end
h2h-convert run <input> [output] [opts]   # conversion (see Phase 3)
```

1. **`setup`**: wraps `pyutagger.downloader.install_utagger` with:
   - a sensible default location under the user profile
     (`%LOCALAPPDATA%\h2h-converter\utagger`, via a tiny hand-rolled platformdirs
     equivalent to stay stdlib-only),
   - a confirmation of disk space / architecture before downloading,
   - on success, writes the install path to a **config file**
     (`%APPDATA%\h2h-converter\config.json`) and prints the `doctor` command to run next.
2. **`doctor`**: checks, in order, each with a ✓/✗ and a one-line remediation:
   - Python version ≥ 3.10 and 64-bit (`struct.calcsize("P") == 8`),
   - UTagger path resolvable (print *which* source resolved it: flag / env / config /
     workspace-local),
   - `bin\UTaggerR64.dll` and `Hlxcfg.txt` exist,
   - DLL loads and `Global_init2` succeeds,
   - live conversion of `대한민국의 역사는 오래되었다.` →
     `대한민국(大韓民國)의 역사(歷史)는 오래되었다.` (the exact check already done by hand
     in `.utagger-live-check.txt` — make it a first-class feature),
   - exits 0 only if everything passed. This becomes the CI smoke test too.
3. **Documented, simplified path resolution precedence** (keep current behavior, but
   add config file and document it):
   `--utagger3-path` > `UTAGGER3_PATH` > config file > pyutagger saved path >
   `.utagger/v3_*` in cwd. `doctor` prints the resolved path and its source.
4. Replace the `RuntimeError("UTagger 3 is not configured...")` chain with a message
   that names the remediation: `Run "h2h-convert setup" or pass --utagger3-path.`

### Phase 3 — Conversion CLI ergonomics (`h2h-convert run`)

> **Status: landed 2026-07-21.** `run` now covers the full daily-use surface:
> default output naming (`<stem>.hanja-ruby.epub`), native batch mode (multiple
> files, folders, and globs via `--output-dir`, one shared UTagger instance,
> existing outputs skipped for resumable batches, folder expansion excludes
> `*.hanja-ruby.epub` so re-running in place is safe, duplicate-output-stem
> guard), per-document TTY-aware progress on stderr (new `progress` callback on
> `convert_epub`), `--preview N` before/after sampling via new
> `collect_epub_texts()` (verified live against the real novel), `--verbose` /
> `--quiet` / `--report FILE` diagnostics, and exit code `5` for partial
> success. Verified end to end: preview on the real sample book, batch
> conversion with real ruby output, exit codes 0/3/5 in live runs. 58 tests
> passing.

1. **Default output name:** if the output argument is omitted, write
   `<stem>.hanja-ruby.epub` next to the input (the convention the PowerShell script
   already uses).
2. **Native batch mode:** accept multiple inputs and/or a directory:
   ```
   h2h-convert run book1.epub book2.epub --output-dir out\
   h2h-convert run "D:\Books\Korean\*.epub" --output-dir out\
   ```
   One `UTaggerHanjaConverter` instance is reused across files (the DLL allows only
   one instance per process — the current PowerShell script already works around this;
   bring that logic into the package).
3. **Progress reporting:** per-document progress during a conversion
   (`doc 12/58: chapter03.xhtml`), plus a per-file summary line. Stderr, TTY-aware:
   redrawn line on a terminal, plain lines when piped. Hand-rolled (or optional
   `tqdm` extra) to stay stdlib-only.
4. **`--preview N`:** convert only the first N text segments and print before/after
   pairs to the console, writing nothing. This is the "what will my book look like?"
   moment and doubles as a quick UTagger sanity check.
5. **Diagnostics control:**
   - `--verbose` / `--quiet`,
   - `--report report.txt` writes the full warning list (no more silent truncation
     at 5),
   - `--strict` stays as-is.
6. **Friendly failure contract:** catch `FileNotFoundError`, `FileExistsError`,
   EPUB structure errors (`ValueError` from container/OPF parsing), and UTagger
   configuration errors; print one concise stderr line each and use documented exit
   codes, e.g. `0` ok, `2` usage error, `3` input/output problem, `4` UTagger problem,
   `5` partial success (some documents preserved unchanged). Tracebacks only with
   `--debug`.
7. Add `--version`.

### Phase 4 — Retire the here-string batch script

> **Status: landed 2026-07-21.** `convert-samples.ps1` no longer contains any
> embedded Python: it resolves the interpreter (unchanged discovery order),
> translates its parameters into a single `python -m h2h_converter run` batch
> call (folder input by default, glob forwarding for `-Filter`, `--overwrite`
> unless `-NoOverwrite`, `--utagger3-path` when explicit or repo-local), and
> maps CLI exit codes — 2/3/4 throw, 5 prints a warning instead of failing.
> Verified live: full batch run (exit 0), `-NoOverwrite` resume (skips reported,
> exit 5 handled), and `-ListOnly`. One code path now exists for batch
> conversion; the script is a convenience, not a parallel implementation.

- Reimplement `convert-samples.ps1` as a thin wrapper over the native batch mode
  (Phase 3.2): resolve the interpreter (Phase 1.3), then call
  `h2h-convert run sample_epubs\*.epub --output-dir data\`.
- This deletes the embedded Python here-string entirely and makes the script a
  convenience, not a parallel implementation to maintain.

### Phase 5 — Documentation rewrite

1. **README, fresh-machine first:** Requirements (Windows x64, Python ≥ 3.10,
   ~200 MB for UTagger data) → Install (venv, `pip install -e ".[setup]"`,
   `h2h-convert setup`, `h2h-convert doctor`) → Convert your first book
   (`h2h-convert run book.epub`) → Options reference → Troubleshooting.
2. **Troubleshooting section** covering the actual failure modes seen so far:
   - DLL not found / wrong architecture (32-bit Python),
   - UTagger data corrupted → re-run `setup`,
   - EPUBs with malformed XHTML → what "preserved unchanged" means and how
     `--strict` / `--report` interact,
   - one-UTagger-instance-per-process limitation (why the batch mode reuses a
     single converter).
3. Move machine-local artifacts (`.utagger/`, `.codex-*`, `.scratch/`, WinPython
   notes) out of the README into a `CONTRIBUTING.md` dev note.
4. Add a `CHANGELOG.md`; start at 0.2.0 when Phase 1–3 land (CLI shape changes are
   breaking: keep `python -m h2h_converter in.epub out.epub` working as an alias for
   `run` during a deprecation window).

### Phase 6 — Reaching non-Python users (strategic, later)

Only after Phases 1–5 stabilize:

1. **PyInstaller one-file build** (`h2h-convert.exe`), ideally bundling the UTagger
   DLL + dictionaries after **verifying UTagger's redistribution license** — that
   check is a hard gate.
2. **Drag-and-drop GUI:** a tiny stdlib Tkinter shell over the same conversion API
   (drop EPUBs onto a window, progress bar, done). Or register a Windows
   "Convert with H2H" Explorer context-menu entry pointing at the exe.
3. Optional watch-folder mode for a "drop books here" directory.

---

## 4. Suggested sequencing

| Step | Phases | Effort | Payoff |
|------|--------|--------|--------|
| 1 | Phase 1 (venv flow, deps, script discovery) + Phase 5 README skeleton | Small | Anyone can install it — removes the WinPython blocker |
| 2 | Phase 2 (`setup` + `doctor` + config file) | Medium | First-run experience becomes self-guided and verifiable |
| 3 | Phase 3 (run subcommand: batch, progress, preview, errors) | Medium | Daily-use ergonomics; subsumes the PowerShell script |
| 4 | Phase 4 (script becomes thin wrapper) | Small | One code path instead of two |
| 5 | Phase 5 full docs + changelog | Small | Maintainability |
| 6 | Phase 6 (exe / GUI) | Large | Non-technical audience — decide based on who actually uses it |

## 5. Success criteria

- Fresh Windows machine: `clone → venv → install → setup → doctor → first conversion`
  in **≤ 5 commands**, none of them containing an absolute machine-specific path.
- `h2h-convert doctor` exits 0 on a healthy install and names the failing step +
  fix on an unhealthy one.
- No file in the repo references `C:\tmp\WinPython`.
- Batch conversion of the sample EPUBs runs without PowerShell embedding Python.
- Every routine failure (existing output, missing input, missing UTagger) prints a
  one-line actionable message with a documented exit code — no tracebacks.
- Existing test suite (`python -m unittest discover -s tests -v`) keeps passing;
  add CLI-level tests for the new subcommands (argparse-only, DLL mocked as in
  `tests/test_utagger.py`).

## 6. Non-goals (for now)

- Replacing the ctypes DLL integration (it works and is offline).
- ~~Linux/macOS support~~ — **revised 2026-07-21 after a WSL experiment:** UTagger 3's
  package ships `bin/UTagger.so` alongside the Windows DLL, and it was verified on
  WSL (Ubuntu, Python 3.10, x86_64) to return output identical to Windows, including
  the `한글(漢字)` line. Linux support needs only a platform-aware library name in
  `utagger.py`/`installer.py`/`doctor.py` plus docs. macOS remains genuinely blocked:
  UTagger ships no Mach-O build and pyutagger's downloader rejects macOS — the only
  routes are a Docker `linux/amd64` container or a lower-quality pure-Python fallback
  engine behind the existing `TextConverter` protocol. ARM64 has no UTagger builds
  (Windows ARM64 → x64 Python emulation; Apple Silicon → the Docker route).
- Changing conversion quality/scope behavior — this plan is UX-only; the core
  pipeline (`epub.py`, `ruby.py`) is untouched by Phases 1–5.

## 7. Addendum — native Linux support (landed 2026-07-21)

What was believed to be a hard blocker ("UTagger is a Windows DLL") turned out to be
~30 lines of platform detection: every UTagger 3 package ships `bin/UTagger.so`
(Linux x86_64) next to `bin/UTaggerR64.dll`. Changes:

- New `utagger3_library_name()` selects the library per OS; used by the loader,
  workspace discovery, `installer.find_utagger3_install`, and `doctor`.
- Config path passed to `Global_init2` uses cp949 on Windows, the filesystem
  encoding (UTF-8) elsewhere.
- `_suppress_native_stdout` now redirects fds 1 **and** 2 and ends with an
  `fflush(NULL)` against the C runtime — the Linux build logs through buffered
  stdio and a worker thread, which leaked without both measures.
- README Requirements/Setup cover Windows + Linux, with macOS/ARM documented as
  container-only. `convert-samples.ps1` is documented as a Windows convenience;
  the native batch mode is the cross-platform path.

Verified end to end in WSL (Ubuntu, Python 3.10.12, x86_64): full test suite
(60/60, same as Windows), `doctor` all checks pass with clean output, and a real
batch conversion producing **byte-identical ruby markup** to the Windows build.
Two test fixtures that used Windows-shaped paths were made platform-aware — the
only cross-platform test breakage found.

Remaining platform gaps (upstream, not ours): no macOS build of UTagger (use a
Linux `amd64` container), no ARM64 builds anywhere.
