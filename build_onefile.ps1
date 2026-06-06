param(
    [switch]$CheckOnly,
    [switch]$NoPause,
    [string]$OutputDir = "dist"
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptRoot "build_support.ps1")
$distDir = if ([System.IO.Path]::IsPathRooted($OutputDir)) { $OutputDir } else { Join-Path $scriptRoot $OutputDir }
$logFileName = if ($CheckOnly) { "build_onefile_check.log" } else { "build_onefile.log" }
$logPath = Join-Path $distDir $logFileName
$pushedLocation = $false

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] $Message"
    Write-Host $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

function Invoke-Native {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )
    Write-Log "Running: $FilePath $($Arguments -join ' ')"
    $oldErrorActionPreference = $ErrorActionPreference
    $hadNativePreference = Test-Path Variable:PSNativeCommandUseErrorActionPreference
    if ($hadNativePreference) {
        $oldNativePreference = $PSNativeCommandUseErrorActionPreference
    }
    try {
        $ErrorActionPreference = "Continue"
        if ($hadNativePreference) {
            $PSNativeCommandUseErrorActionPreference = $false
        }
        $output = & $FilePath @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldErrorActionPreference
        if ($hadNativePreference) {
            $PSNativeCommandUseErrorActionPreference = $oldNativePreference
        }
    }
    foreach ($line in $output) {
        if ($line -is [System.Management.Automation.ErrorRecord]) {
            $text = $line.Exception.Message
        }
        else {
            $text = $line.ToString()
        }
        if ([string]::IsNullOrWhiteSpace($text) -or $text -eq "System.Management.Automation.RemoteException") {
            continue
        }
        Write-Host $text
        Add-Content -LiteralPath $logPath -Value $text -Encoding UTF8
    }
    if ($null -eq $exitCode) {
        $exitCode = 0
    }
    if ($exitCode -ne 0) {
        throw "Command failed with exit code $exitCode`: $FilePath $($Arguments -join ' ')"
    }
}

function Remove-StaleOnefileOutputs {
    $targets = @()
    $exePath = Join-Path $distDir "BedScrewSolverV4.exe"
    if (Test-Path -LiteralPath $exePath) {
        $targets += $exePath
    }
    $targets += @(Get-ChildItem -LiteralPath $distDir -Filter "RC*.tmp" -File -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)

    foreach ($target in $targets) {
        $resolved = Resolve-Path -LiteralPath $target -ErrorAction SilentlyContinue
        if ($null -eq $resolved) {
            continue
        }
        if (-not $resolved.Path.StartsWith($distDir, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove unexpected path outside dist: $($resolved.Path)"
        }
        Write-Log "Removing stale build output: $($resolved.Path)"
        Remove-Item -LiteralPath $resolved.Path -Force
    }
}

function Test-PyLauncherVersion {
    param([string]$Version)
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        return $false
    }

    $oldErrorActionPreference = $ErrorActionPreference
    $hadNativePreference = Test-Path Variable:PSNativeCommandUseErrorActionPreference
    if ($hadNativePreference) {
        $oldNativePreference = $PSNativeCommandUseErrorActionPreference
    }

    try {
        $ErrorActionPreference = "Continue"
        if ($hadNativePreference) {
            $PSNativeCommandUseErrorActionPreference = $false
        }
        & py "-$Version" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == tuple(map(int, '$Version'.split('.'))) else 1)" *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
    finally {
        $ErrorActionPreference = $oldErrorActionPreference
        if ($hadNativePreference) {
            $PSNativeCommandUseErrorActionPreference = $oldNativePreference
        }
    }
}

function Resolve-BuildPython {
    $resolved = Resolve-ProjectPython -Root $scriptRoot
    Write-Log "Using Python from $($resolved.Source) for Nuitka onefile build."
    return $resolved
}

try {
    New-Item -ItemType Directory -Force -Path $distDir | Out-Null
    Set-Content -LiteralPath $logPath -Value "Bed Screw Solver V4 onefile build log" -Encoding UTF8

    Push-Location $scriptRoot
    $pushedLocation = $true
    Write-Log "Build root: $scriptRoot"

    $python = Resolve-BuildPython
    $pythonExe = [string]$python.Exe
    $pythonArgs = [string[]]$python.Args

    Invoke-Native $pythonExe ($pythonArgs + @("-c", "import sys; print(sys.executable); print(sys.version)"))

    if ($CheckOnly) {
        Invoke-Native $pythonExe ($pythonArgs + @("-c", "import PySide6, numpy, nuitka; print('Build imports OK')"))
        Write-Log "Check-only mode completed. No executable was built."
        exit 0
    }

    Remove-StaleOnefileOutputs
    Invoke-Native $pythonExe ($pythonArgs + @("-m", "pip", "install", "-r", "requirements.txt"))
    Invoke-Native $pythonExe ($pythonArgs + @("-m", "pip", "install", "Nuitka[onefile]"))

    $nuitkaArgs = @(
        "-m", "nuitka",
        "--onefile",
        "--enable-plugin=pyside6",
        "--include-data-dir=assets=assets",
        "--windows-console-mode=disable",
        "--include-windows-runtime-dlls=yes",
        "--assume-yes-for-downloads",
        "--output-dir=dist",
        "--output-filename=BedScrewSolverV4",
        "main.py"
    )

    try {
        Invoke-Native $pythonExe ($pythonArgs + $nuitkaArgs)
    }
    catch {
        Write-Log "Compressed onefile build failed. Retrying once with --onefile-no-compression to avoid antivirus/resource-lock issues."
        Remove-StaleOnefileOutputs
        $nuitkaNoCompressionArgs = $nuitkaArgs[0..($nuitkaArgs.Count - 2)] + @("--onefile-no-compression") + $nuitkaArgs[-1]
        Invoke-Native $pythonExe ($pythonArgs + $nuitkaNoCompressionArgs)
    }

    Write-Log "Build completed: $(Join-Path $distDir 'BedScrewSolverV4.exe')"
    exit 0
}
catch {
    $message = $_.Exception.Message
    Write-Host ""
    Write-Host "Onefile build failed." -ForegroundColor Red
    Write-Host $message -ForegroundColor Red
    Write-Host "Log file: $logPath"
    Add-Content -LiteralPath $logPath -Value "[ERROR] $message" -Encoding UTF8
    if (-not $NoPause) {
        Read-Host "Press Enter to exit"
    }
    exit 1
}
finally {
    if ($pushedLocation) {
        Pop-Location
    }
}
