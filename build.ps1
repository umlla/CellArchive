param(
    [switch]$Frontend
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$version = '4.0.0'
$release = Join-Path $root 'release'
if (-not $env:GOCACHE) { $env:GOCACHE = Join-Path $root '.tools\gocache' }
$go = (Get-Command go -ErrorAction SilentlyContinue).Source
if (-not $go -and (Test-Path (Join-Path $root '.tools\go\bin\go.exe'))) {
    $go = Join-Path $root '.tools\go\bin\go.exe'
}
if (-not $go) {
    Write-Host '未找到 Go。请先安装 Go 1.26+，或把 Go 解压到 .tools\go。' -ForegroundColor Red
    exit 1
}

function New-ZipPackage {
    param(
        [string]$SourceDir,
        [string]$Destination
    )
    Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
    if (Test-Path $Destination) { Remove-Item $Destination -Force }
    $zip = [IO.Compression.ZipFile]::Open($Destination, [IO.Compression.ZipArchiveMode]::Create)
    try {
        Get-ChildItem -Path $SourceDir -Recurse -File | ForEach-Object {
            $relative = $_.FullName.Substring($SourceDir.Length).TrimStart('\', '/').Replace('\', '/')
            $entry = $zip.CreateEntry($relative, [IO.Compression.CompressionLevel]::Optimal)
            $entry.ExternalAttributes = [int]0x81A40000   # 0100644
            $input = [IO.File]::OpenRead($_.FullName)
            $output = $entry.Open()
            try { $input.CopyTo($output) } finally { $output.Dispose(); $input.Dispose() }
        }
    } finally {
        $zip.Dispose()
    }
}

if ($Frontend) {
    Write-Host '[frontend] 构建 Vue 页面...'
    Push-Location (Join-Path $root 'frontend')
    npm install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
    npm run build
    if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
    Pop-Location
    if (Test-Path (Join-Path $root 'web\dist')) {
        Remove-Item (Join-Path $root 'web\dist') -Recurse -Force
    }
    Copy-Item (Join-Path $root 'frontend\dist') (Join-Path $root 'web\dist') -Recurse
    Copy-Item (Join-Path $root 'assets\app.ico') (Join-Path $root 'web\dist\favicon.ico') -Force
}

if (-not (Test-Path (Join-Path $root 'web\dist\index.html'))) {
    Write-Host '缺少 web\dist\index.html。请先运行 build.ps1 -Frontend。' -ForegroundColor Red
    exit 1
}

if (Test-Path $release) { Remove-Item $release -Recurse -Force }
New-Item -ItemType Directory -Force -Path $release | Out-Null

$env:CGO_ENABLED = '0'
$env:GOOS = 'windows'
$env:GOARCH = 'amd64'
$ldflags = '-s -w'

Write-Host '[windows] 构建 64 位程序...'
$winDir = Join-Path $release 'CellTracker-win64'
New-Item -ItemType Directory -Force -Path $winDir | Out-Null
& $go build -trimpath -ldflags $ldflags -o (Join-Path $winDir 'CellTracker.exe') .\cmd\celltracker
if ($LASTEXITCODE -ne 0) { exit 1 }
Copy-Item README.md (Join-Path $winDir 'README.md') -Force
Copy-Item LICENSE (Join-Path $winDir 'LICENSE') -Force
Copy-Item config.example.json (Join-Path $winDir 'config.example.json') -Force
Copy-Item packaging\README-win.txt (Join-Path $winDir 'README.txt') -Force
New-ZipPackage -SourceDir $winDir -Destination (Join-Path $release "CellTracker-$version-win64.zip")

Get-ChildItem $release -File | Where-Object { $_.Extension -in '.zip', '.exe' } | ForEach-Object {
    $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
    "$hash  $($_.Name)"
} | Set-Content (Join-Path $release 'SHA256SUMS.txt') -Encoding ASCII

Write-Host ''
Write-Host '构建完成，文件在 release 目录：' -ForegroundColor Green
Get-ChildItem $release | Select-Object Name, Length | Format-Table -AutoSize
