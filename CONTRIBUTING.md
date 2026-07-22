# Contributing

## Development setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
python -m unittest discover -s tests -v
```

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m unittest discover -s tests -v
```

The `setup` extra (`pip install -e ".[setup]"`) is only needed for
`h2h-convert setup`, i.e. downloading UTagger — not for development or tests.

## Testing notes

- The test suite mocks the native library (see `tests/test_utagger.py` and the
  fakes in `tests/test_cli.py`), so it runs anywhere without UTagger installed.
  Keep it that way: new tests must not require the real `.dll`/`.so`.
- The suite passes on both Windows and Linux — run it in WSL before merging
  changes that touch `utagger.py`, `installer.py`, or `doctor.py`.

## Live verification with the real UTagger install

The repo-local `.utagger/v3_2109b` install plus `sample_epubs/` allow full
end-to-end checks without any extra setup:

```powershell
python -m h2h_converter doctor
python -m h2h_converter run "sample_epubs\소년이 온다 (한강).epub" --preview 5
python -m h2h_converter run .scratch\live-in --output-dir .scratch\live-out
```

Linux verification was done in WSL (Ubuntu, Python 3.10) the same way; the
batch output was byte-identical to the Windows build. `.utagger-live-check.txt`
records the original offline check (sockets blocked, conversion still worked).

## Repo-local artifacts (git-ignored, do not commit)

- `.utagger/` — local UTagger installs (`v3_2109b` is used; `v4_2403b` is
  experimental and not supported by the converter)
- `.codex-py-pkgs/`, `.codex-home/` — sandboxes from earlier agent-assisted
  development
- `.scratch/` — throwaway outputs: live conversion fixtures, the pyutagger
  wheel inspection, timing runs
- `data/` — output of `convert-samples.ps1`

## Historical note

Early development ran against a portable WinPython install at a machine-local
path (`C:\tmp\WinPython\...`). Version 0.2.0 replaced that with the standard
venv flow; no file in the repo should reference machine-specific interpreter
paths.
