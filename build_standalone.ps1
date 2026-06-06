param(
    [switch]$CheckOnly,
    [string]$OutputDir = "dist"
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptRoot "build_support.ps1")

$python = Resolve-ProjectPython -Root $scriptRoot
$pythonExe = [string]$python.Exe
$pythonArgs = [string[]]$python.Args
Write-Host "Using Python from $($python.Source): $pythonExe $($pythonArgs -join ' ')"

if ($CheckOnly) {
    & $pythonExe @pythonArgs -c "import PySide6, numpy, nuitka; print('Build imports OK')"
    exit $LASTEXITCODE
}

$resolvedOutputDir = if ([System.IO.Path]::IsPathRooted($OutputDir)) { $OutputDir } else { Join-Path $scriptRoot $OutputDir }

& $pythonExe @pythonArgs -m pip install -r requirements.txt
& $pythonExe @pythonArgs -m nuitka `
    --standalone `
    --enable-plugin=pyside6 `
    --include-data-dir=assets=assets `
    --windows-console-mode=disable `
    --assume-yes-for-downloads `
    --output-dir=$resolvedOutputDir `
    --output-filename=BedScrewSolverV4 `
    main.py
