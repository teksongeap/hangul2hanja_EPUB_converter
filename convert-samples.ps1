param(
    [string]$InputDir = (Join-Path $PSScriptRoot "sample_epubs"),
    [string]$OutputDir = (Join-Path $PSScriptRoot "data"),
    [Alias("Filter")]
    [string]$NamePattern = "*.epub",
    [string]$UTaggerPath = "",
    [string]$PythonPath = "",
    [switch]$ListOnly,
    [switch]$NoOverwrite
)

$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

function Resolve-PythonInterpreter {
    if ($PythonPath) {
        if (-not (Test-Path -LiteralPath $PythonPath)) {
            throw "Python interpreter not found: $PythonPath"
        }
        return $PythonPath
    }
    if ($env:H2H_PYTHON) {
        if (-not (Test-Path -LiteralPath $env:H2H_PYTHON)) {
            throw "H2H_PYTHON points to a missing interpreter: $env:H2H_PYTHON"
        }
        return $env:H2H_PYTHON
    }
    $venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        return $venvPython
    }
    $onPath = Get-Command python -ErrorAction SilentlyContinue
    if ($onPath) {
        return $onPath.Source
    }
    throw "No Python interpreter found. Set one up first: py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -e `".[setup]`""
}

$python = Resolve-PythonInterpreter

if (-not (Test-Path -LiteralPath $InputDir)) {
    throw "Sample EPUB folder not found: $InputDir"
}

# An explicit UTagger path is validated up front. With no explicit path, prefer the
# repo-local install when it exists, and otherwise let the converter resolve UTagger
# itself (UTAGGER3_PATH, pyutagger's saved path, etc.).
$utaggerArg = ""
if ($UTaggerPath) {
    if (-not (Test-Path -LiteralPath $UTaggerPath)) {
        throw "UTagger folder not found: $UTaggerPath"
    }
    $utaggerArg = $UTaggerPath
} else {
    $localInstall = Join-Path $PSScriptRoot ".utagger\v3_2109b"
    if (Test-Path -LiteralPath $localInstall) {
        $utaggerArg = $localInstall
    }
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$epubs = Get-ChildItem -LiteralPath $InputDir -Filter "*.epub" -File |
    Where-Object { $_.Name -like $NamePattern }
if ($epubs.Count -eq 0) {
    Write-Host "No EPUB files found in $InputDir matching $NamePattern"
    exit 0
}

if ($ListOnly) {
    $epubs | ForEach-Object { Write-Host $_.Name }
    exit 0
}

$env:PYTHONIOENCODING = "utf-8"
$overwrite = if ($NoOverwrite) { "0" } else { "1" }
$converterScript = @'
from __future__ import annotations

from pathlib import Path
import sys

from h2h_converter.epub import convert_epub
from h2h_converter.utagger import UTaggerHanjaConverter, UTaggerOptions


output_dir = Path(sys.argv[1])
raw_utagger_path = sys.argv[2]
utagger_path = Path(raw_utagger_path) if raw_utagger_path else None
overwrite = sys.argv[3] == "1"
epubs = [Path(raw_path) for raw_path in sys.argv[4:]]

with UTaggerHanjaConverter(UTaggerOptions(utagger3_path=utagger_path)) as converter:
    for index, epub in enumerate(epubs, start=1):
        output_path = output_dir / f"{epub.stem}.hanja-ruby.epub"
        print(f"[{index}/{len(epubs)}] Converting {epub.name} -> {output_path}", flush=True)
        stats = convert_epub(epub, output_path, converter, overwrite=overwrite)
        print(
            "  "
            f"{stats.documents} document(s), "
            f"{stats.text_nodes} text segment(s), "
            f"{stats.ruby_nodes} ruby annotation(s)",
            flush=True,
        )
        if stats.skipped_documents:
            print(f"  preserved {stats.skipped_documents} document(s) unchanged", flush=True)
        for warning in stats.warnings[:5]:
            print(f"  warning: {warning}", flush=True)
        if len(stats.warnings) > 5:
            print(f"  warning: {len(stats.warnings) - 5} more warning(s) omitted", flush=True)
'@

& $python -c $converterScript $OutputDir $utaggerArg $overwrite @($epubs.FullName)
if ($LASTEXITCODE -ne 0) {
    throw "Sample conversion failed"
}

Write-Host "Done. Converted $($epubs.Count) EPUB file(s) into $OutputDir"
