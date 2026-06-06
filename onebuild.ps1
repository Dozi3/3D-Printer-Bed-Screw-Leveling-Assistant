$builder = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "build_onefile.ps1"
& $builder @args
exit $LASTEXITCODE
