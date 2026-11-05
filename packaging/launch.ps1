$ErrorActionPreference = 'Stop'
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$exe = Join-Path $dir 'CellTracker.exe'
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $exe
$psi.WorkingDirectory = $dir
$psi.UseShellExecute = $false
[System.Diagnostics.Process]::Start($psi) | Out-Null
