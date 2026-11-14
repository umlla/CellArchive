# 细胞档案 CellArchive v4 · 内测版（Python）
# 把源码打成可拷贝的干净压缩包（不含虚拟环境、node_modules、数据库、密钥）
#
# 用法：
#   pwsh -File packaging\make-source-zip.ps1
#
# 产物：release\CellArchive-internal-source.zip

param(
    [string]$Output = 'release\CellArchive-internal-source.zip'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$outputPath = Join-Path $root $Output
$outputDir = Split-Path -Parent $outputPath
if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}

# 需要打进包里的目录与文件（白名单，避免误带敏感数据）
$includeDirs = @('backend', 'frontend', 'docs', 'packaging')
$includeFiles = @(
    'start.command',
    'start.bat',
    'run.py',
    'README.md',
    'LICENSE',
    'config.example.json',
    'pytest.ini'
)

# 白名单目录里仍要排除的（构建产物/缓存/依赖）
$excludePatterns = @(
    '*\node_modules\*',
    '*\__pycache__\*',
    '*\.venv\*',
    '*\dist\*',
    '*\.pytest_cache\*',
    '*\*.pyc'
)

$staging = Join-Path $root '.build\source-staging'
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory -Path $staging -Force | Out-Null

$copied = 0

foreach ($file in $includeFiles) {
    if (Test-Path (Join-Path $root $file)) {
        Copy-Item (Join-Path $root $file) -Destination $staging
        $copied++
    } else {
        Write-Host "  跳过（不存在）：$file" -ForegroundColor Yellow
    }
}

foreach ($dir in $includeDirs) {
    $source = Join-Path $root $dir
    if (-not (Test-Path $source)) { continue }
    $target = Join-Path $staging $dir
    New-Item -ItemType Directory -Path $target -Force | Out-Null

    $files = Get-ChildItem -Path $source -Recurse -File
    foreach ($f in $files) {
        $relative = $f.FullName.Substring($root.Length + 1)
        $skip = $false
        foreach ($pattern in $excludePatterns) {
            if ($relative -like $pattern) { $skip = $true; break }
        }
        if ($skip) { continue }

        $destFile = Join-Path $staging $relative
        $destDir = Split-Path -Parent $destFile
        if (-not (Test-Path $destDir)) {
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        }
        Copy-Item $f.FullName -Destination $destFile
        $copied++
    }
}

# 前端构建产物单独判断：dist 被排除了，但 Mac 上可以重建。
# 这里提示一下，避免同事没有 Node 时卡住。
$hasDist = Test-Path (Join-Path $root 'frontend\dist\index.html')

if (Test-Path $outputPath) { Remove-Item -Force $outputPath }
Compress-Archive -Path (Join-Path $staging '*') -DestinationPath $outputPath -CompressionLevel Optimal

Remove-Item -Recurse -Force $staging

$sizeMb = [math]::Round((Get-Item $outputPath).Length / 1MB, 2)
Write-Host ""
Write-Host "已生成：$outputPath" -ForegroundColor Green
Write-Host "  文件数：$copied"
Write-Host "  大小：$sizeMb MB"
Write-Host ""
if (-not $hasDist) {
    Write-Host "注意：本地没有 frontend\dist，包里也不含构建产物。" -ForegroundColor Yellow
    Write-Host "      Mac 上首次运行 start.command 时会自动构建（需要 Node.js）。" -ForegroundColor Yellow
}
Write-Host "包里不含：.venv、node_modules、data/、config.json、密钥（符合 .gitignore）"
