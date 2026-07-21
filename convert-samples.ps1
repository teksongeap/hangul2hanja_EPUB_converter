# Thin wrapper around the CLI's native batch mode: converts every EPUB in a
# folder into <name>.hanja-ruby.epub. Kept for convenience on Windows; the same
# job works everywhere with: h2h-convert run <folder> --output-dir <dir>
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

if ($ListOnly) {
    Get-ChildItem -LiteralPath $InputDir -Filter "*.epub" -File |
        Where-Object { $_.Name -like $NamePattern } |
        ForEach-Object { Write-Host $_.Name }
    exit 0
}

# An explicit UTagger path is validated up front. With no explicit path, prefer the
# repo-local install when it exists, and otherwise let the converter resolve UTagger
# itself (UTAGGER3_PATH, config file, pyutagger's saved path).
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

$cliArgs = [System.Collections.Generic.List[string]]::new()
$cliArgs.Add("-m")
$cliArgs.Add("h2h_converter")
$cliArgs.Add("run")
# Folder input lets the CLI skip its own *.hanja-ruby.epub outputs; a custom
# name pattern is forwarded as a glob the CLI expands itself.
if ($NamePattern -eq "*.epub") {
    $cliArgs.Add($InputDir)
} else {
    $cliArgs.Add((Join-Path $InputDir $NamePattern))
}
$cliArgs.Add("--output-dir")
$cliArgs.Add($OutputDir)
if (-not $NoOverwrite) {
    $cliArgs.Add("--overwrite")
}
if ($utaggerArg) {
    $cliArgs.Add("--utagger3-path")
    $cliArgs.Add($utaggerArg)
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

& $python @cliArgs
$exitCode = $LASTEXITCODE

# CLI exit codes: 0 ok, 2 usage, 3 input/output, 4 UTagger, 5 partial success.
if ($exitCode -in 2, 3, 4) {
    throw "Sample conversion failed (exit code $exitCode)"
}
if ($exitCode -eq 5) {
    Write-Host "Finished with skipped files or warnings (exit code 5) - see the output above."
}

Write-Host "Done. Converted EPUBs from $InputDir into $OutputDir"
