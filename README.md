# H2H Converter

Convert Korean-language EPUBs into enhanced EPUBs with Hanja shown as ruby text above Sino-Korean words.

This project now uses UTagger instead of the old experimental TensorFlow model. UTagger does the hard Korean morphological analysis and Hangul-to-Hanja disambiguation locally after its dictionaries have been installed. The converter loads UTagger 3's native DLL directly; `pyutagger` is useful for downloading UTagger, but is not needed at conversion time.

## Status

This is an early working pipeline:

- Reads an EPUB as a ZIP archive.
- Finds the OPF package and spine XHTML files.
- Sends Korean text nodes to local UTagger 3.
- Uses UTagger's `hangul_to_hanja 2` output, for example `역사(歷史)`.
- Rewrites that notation as XHTML ruby:

```html
<ruby>역사<rp>(</rp><rt>歷史</rt><rp>)</rp></ruby>
```

The converter now works at paragraph-like block scope where possible, so words split across inline tags can still be annotated. It falls back to smaller text-node conversion outside normal reading blocks.

## Requirements

- Windows 10/11 (x64) or Linux (x86_64). UTagger ships 64-bit x86 native
  libraries for both (`UTaggerR64.dll` / `UTagger.so`), and the converter
  loads whichever matches your OS; 32-bit Python cannot load them.
  - ARM64 Windows: use x64 Python under emulation.
  - macOS: not supported natively (UTagger has no macOS build). The practical
    route is a Linux `amd64` container, which also works on Apple Silicon.
- CPython 3.10–3.13, 64-bit.
- About 200 MB of disk space for the UTagger 3 binaries and dictionaries.

## Setup

Create a virtual environment and install the package:

```powershell
# Windows PowerShell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[setup]"
```

```bash
# Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[setup]"
```

The `setup` extra installs `pyutagger`, which is used only to download UTagger. The converter itself has no runtime dependencies.

### Install UTagger 3 data

```powershell
h2h-convert setup
```

This downloads the UTagger 3 binaries and dictionaries into your per-user data
directory (`%LOCALAPPDATA%\h2h-converter\utagger` on Windows,
`~/.local/share/h2h-converter/utagger` on Linux) and saves the location to a
config file. Use `--install-dir DIR` to install elsewhere. If a usable install
already exists in that directory, `setup` reuses it instead of downloading again.

Then verify the whole chain end to end:

```powershell
h2h-convert doctor
```

`doctor` checks your Python version and architecture, finds UTagger (telling you
*which* source supplied the path), loads the DLL, and runs a live conversion.
It exits with code 0 only when everything works.

You can also install UTagger manually with `pyutagger`:

```powershell
python -c "import pyutagger.downloader as d; d.install_utagger('utagger3', r'C:\utagger')"
```

At conversion time the converter looks for UTagger 3 in this order:

1. `--utagger3-path` on the command line
2. The `UTAGGER3_PATH` environment variable
3. The h2h-converter config file (written by `h2h-convert setup`)
4. The path saved by `pyutagger` when it installed UTagger
5. A `.utagger\v3_*` folder in the current working directory

## Offline Use

The first UTagger install downloads native binaries and dictionaries. After that, conversion is local: the converter loads UTagger's DLL and dictionary files from disk.

We verified this locally by blocking Python socket creation and converting sample Korean text through UTagger 3 successfully:

```text
대한민국의 역사는 오래되었다.
대한민국(大韓民國)의 역사(歷史)는 오래되었다.
```

## Convert An EPUB

```powershell
h2h-convert run input.epub
```

With no output argument the converter writes `input.hanja-ruby.epub` next to the
input. You can also name the output explicitly:

```powershell
h2h-convert run input.epub output.epub --overwrite
```

(`h2h-convert input.epub output.epub` without `run` still works but is
deprecated; `python -m h2h_converter ...` is equivalent to `h2h-convert ...`.)

### Preview before converting

```powershell
h2h-convert run input.epub --preview
```

Prints before/after pairs for the first 10 Korean text segments (use
`--preview N` for more) without writing an output file — a quick way to see
what the annotations will look like.

### Batch conversion

```powershell
h2h-convert run book1.epub book2.epub --output-dir out
h2h-convert run "D:\Books\Korean\*.epub" --output-dir out
h2h-convert run D:\Books\Korean --output-dir out
```

Every input becomes `<name>.hanja-ruby.epub` in the output folder, converted
with a single shared UTagger instance. Existing outputs are skipped (so batches
are resumable) unless `--overwrite` is given; folder expansion automatically
skips `*.hanja-ruby.epub` files so re-running a batch in place is safe.

### Progress, warnings, reports

Per-document progress is shown while converting (a live line on the terminal,
plain lines when piped). Warnings are truncated to 5 on screen by default:

- `--verbose` prints every warning
- `--quiet` suppresses progress and summaries (errors only)
- `--report report.txt` writes the full warning list to a file

### Other options

```powershell
h2h-convert run input.epub --utagger3-path C:\utagger\v3_2109b --overwrite
h2h-convert run input.epub output.epub --hanja-levels "0 1 2 3 4 5"
```

By default, malformed spine documents that cannot be parsed as XHTML/XML are preserved unchanged and reported as warnings. Use `--strict` to stop at the first parse error instead.

Exit codes: `0` success, `2` usage error, `3` input/output problem (missing
input, existing output, unreadable EPUB, nothing converted), `4` UTagger
problem, `5` partial success (converted, but some documents were preserved
unchanged or some files were skipped/failed).

## Troubleshooting

**`doctor` says the UTagger 3 install location could not be resolved.**
Run `h2h-convert setup`, or point at an existing install with `--utagger3-path`
/ `UTAGGER3_PATH`. When resolution succeeds, `doctor` tells you which source
supplied the path.

**"UTagger library not found" or a missing `Hlxcfg.txt`.**
The install is incomplete or corrupted. Re-run `h2h-convert setup` — it reuses
what it can and re-downloads the rest.

**`doctor` fails the 64-bit check.**
UTagger ships 64-bit x86 libraries only. Install 64-bit CPython and recreate
your virtual environment (on ARM64 Windows, use x64 Python under emulation).

**"Output already exists".**
Pass `--overwrite`. In batch mode existing outputs are skipped automatically,
so re-running a batch resumes where it stopped.

**"Preserved N document(s) unchanged" warnings.**
Those spine documents are not well-formed XHTML/XML, so they were copied
verbatim while everything else was converted normally. Use `--report FILE` for
the full list, or `--strict` to abort on the first such document instead.

**A large book takes minutes to convert.**
UTagger morphologically analyzes every paragraph; a full novel can take
several minutes. Per-document progress is shown while it works, and
`--preview` lets you check annotation quality before committing to a whole book.

**"Only one UTagger 3 instance can be loaded per process."**
The native library allows a single instance; the CLI's batch mode therefore
reuses one converter across all files. Separate `h2h-convert` processes each
get their own instance (on Linux the dictionaries are shared via shared
memory).

**Korean text looks garbled in an old console.**
The CLI writes UTF-8 when piped and uses the Unicode console API on a
terminal; on legacy consoles use Windows Terminal or PowerShell 7.

**macOS or ARM64.**
UTagger has no macOS or ARM build. The practical route is a Linux `amd64`
container (works on Apple Silicon via Rosetta).

## Pipeline

1. Unpack the EPUB in memory.
2. Read `META-INF/container.xml`.
3. Locate the OPF package file.
4. Resolve spine XHTML files from the manifest.
5. Parse each XHTML document, repairing common named HTML entities such as `&nbsp;`.
6. Skip unsafe or unsuitable areas such as `script`, `style`, existing `ruby`, `pre`, and `code`.
7. Convert paragraph-like Hangul text with local UTagger 3 in 병기 mode.
8. Align `한글(漢字)` output back to the original XHTML text runs and replace the Hangul base with `<ruby>` markup.
9. Inject a small ruby stylesheet unless `--no-css` is passed.
10. Repack the EPUB while preserving the required uncompressed `mimetype` entry.

## Development

Install the package (no extras needed for the test suite):

```powershell
pip install -e .
python -m unittest discover -s tests -v
```

To convert every sample EPUB under `sample_epubs/` into `data/`:

```powershell
.\convert-samples.ps1
```

(This helper script is Windows-only and is a thin wrapper around
`python -m h2h_converter run`; everywhere else the native batch mode does the
same job directly: `h2h-convert run sample_epubs --output-dir data`.)

The script finds Python in this order: the `-PythonPath` parameter, the `H2H_PYTHON` environment variable, `.venv\Scripts\python.exe`, then `python` on PATH. It passes an explicit UTagger path only when you give it one with `-UTaggerPath` or when the repo-local `.utagger\v3_2109b` folder exists; otherwise the converter's normal resolution order applies. Exit code 5 from the CLI (skipped files / preserved documents) is reported as a warning, not a failure.

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing notes,
live-verification recipes, and the list of machine-local artifacts that are
intentionally git-ignored. Release history lives in
[CHANGELOG.md](CHANGELOG.md).
