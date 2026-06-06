param(
    [switch]$SkipBuildCheck
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptRoot "build_support.ps1")

function Invoke-ValidationStep {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$Arguments
    )

    Write-Host ""
    Write-Host "== $Name ==" -ForegroundColor Cyan
    Write-Host "$FilePath $($Arguments -join ' ')"
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE."
    }
}

Push-Location $scriptRoot
try {
    $python = Resolve-ProjectPython -Root $scriptRoot
    $pythonExe = [string]$python.Exe
    $pythonArgs = [string[]]$python.Args
    Write-Host "Using Python from $($python.Source): $pythonExe $($pythonArgs -join ' ')"

    if (-not $env:QT_QPA_PLATFORM) {
        $env:QT_QPA_PLATFORM = "offscreen"
    }

    Invoke-ValidationStep `
        -Name "Dependency imports" `
        -FilePath $pythonExe `
        -Arguments ($pythonArgs + @("-c", "import PySide6, numpy, nuitka; print('Dependency imports OK')"))

    Invoke-ValidationStep `
        -Name "Compile all" `
        -FilePath $pythonExe `
        -Arguments (
            $pythonArgs + @(
                "-m",
                "compileall",
                "analysis.py",
                "calibration.py",
                "component_library.py",
                "main.py",
                "materials.py",
                "mechanics.py",
                "mesh_io.py",
                "models.py",
                "project_io.py",
                "solver.py",
                "warp.py",
                "widgets",
                "tests"
            )
        )

    Invoke-ValidationStep `
        -Name "Unit tests" `
        -FilePath $pythonExe `
        -Arguments ($pythonArgs + @("-m", "unittest", "discover", "-s", "tests", "-v"))

    if (-not $SkipBuildCheck) {
        Write-Host ""
        Write-Host "== Onefile build check ==" -ForegroundColor Cyan
        & (Join-Path $scriptRoot "build_onefile.ps1") -CheckOnly -NoPause -OutputDir "dist-validation\onefile-check"
        if ($LASTEXITCODE -ne 0) {
            throw "Onefile build check failed with exit code $LASTEXITCODE."
        }
    }

    Write-Host ""
    Write-Host "Validation completed successfully." -ForegroundColor Green
}
finally {
    Pop-Location
}
