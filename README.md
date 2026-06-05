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

## Setup

Use Python 3.10 or newer. On this machine, the portable Python path is:

```powershell
C:\tmp\WinPython\WPy64-3.13.12.0\python\python.exe
```

Install setup dependencies if you want to use `pyutagger` to download UTagger:

```powershell
python -m pip install -r requirements.txt
```

Install UTagger 3 data with `pyutagger`:

```powershell
python -c "import pyutagger.downloader as d; d.install_utagger('utagger3', r'C:\utagger')"
```

You can install UTagger elsewhere. If pyutagger has saved the install path, the converter will find it automatically. Otherwise pass `--utagger3-path`.

## Offline Use

The first UTagger install downloads native binaries and dictionaries. After that, conversion is local: the converter loads UTagger's DLL and dictionary files from disk.

We verified this locally by blocking Python socket creation and converting sample Korean text through UTagger 3 successfully:

```text
대한민국의 역사는 오래되었다.
대한민국(大韓民國)의 역사(歷史)는 오래되었다.
```

## Convert An EPUB

```powershell
python -m h2h_converter input.epub output.hanja-ruby.epub --overwrite
```

With an explicit UTagger 3 path:

```powershell
python -m h2h_converter input.epub output.hanja-ruby.epub --utagger3-path C:\utagger\v3_2109b --overwrite
```

Optional Hanja level filtering:

```powershell
python -m h2h_converter input.epub output.epub --hanja-levels "0 1 2 3 4 5"
```

By default, malformed spine documents that cannot be parsed as XHTML/XML are preserved unchanged and reported as warnings. Use `--strict` to stop at the first parse error instead.

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

Run tests:

```powershell
python -m unittest discover -s tests -v
```

The local folders `.utagger/`, `.codex-py-pkgs/`, `.codex-home/`, `.scratch/`, and UTagger check outputs are ignored because they are machine-local verification artifacts.
