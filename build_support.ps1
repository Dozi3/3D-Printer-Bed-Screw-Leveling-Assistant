$ErrorActionPreference = "Stop"

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

function Resolve-ProjectPython {
    param(
        [string]$Root = $PSScriptRoot,
        [switch]$PreferPython3Command
    )

    $windowsVenv = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $windowsVenv) {
        return @{ Exe = $windowsVenv; Args = @(); Source = "workspace .venv" }
    }

    $posixVenv = Join-Path $Root ".venv/bin/python"
    if (Test-Path -LiteralPath $posixVenv) {
        return @{ Exe = $posixVenv; Args = @(); Source = "workspace .venv" }
    }

    if ($env:GITHUB_ACTIONS -eq "true" -and (Get-Command python -ErrorAction SilentlyContinue)) {
        return @{ Exe = "python"; Args = @(); Source = "python on PATH from GitHub Actions" }
    }

    if (-not $PreferPython3Command) {
        foreach ($version in @("3.13", "3.12", "3")) {
            if (Test-PyLauncherVersion $version) {
                return @{ Exe = "py"; Args = @("-$version"); Source = "Python launcher $version" }
            }
        }
    }

    if ($PreferPython3Command -and (Get-Command python3 -ErrorAction SilentlyContinue)) {
        return @{ Exe = "python3"; Args = @(); Source = "python3 on PATH" }
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @{ Exe = "python"; Args = @(); Source = "python on PATH" }
    }

    if ($PreferPython3Command -and (Get-Command py -ErrorAction SilentlyContinue)) {
        foreach ($version in @("3.13", "3.12", "3")) {
            if (Test-PyLauncherVersion $version) {
                return @{ Exe = "py"; Args = @("-$version"); Source = "Python launcher $version" }
            }
        }
    }

    throw "Python was not found. Create .venv first, install Python for the py launcher, or put python on PATH."
}
